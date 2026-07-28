// Stage 8 specialist composition. The group shell owns navigation and overview
// data; the existing app modules continue to own their full, proven screens.

import { confirm as confirmDialog } from './dialog.js';
import { calendarDateKey, formatDateParts, formatDateTime } from './i18n.js';
import { disposePlanBoard, renderPlanBoard } from './plan_board.js';

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
export const SPECIALIST_SIDEBAR_STORAGE_KEY = 'alles-specialist-sidebar-hidden';

function _storedSidebarCollapsed() {
  try { return window.localStorage.getItem(SPECIALIST_SIDEBAR_STORAGE_KEY) === '1'; }
  catch { return false; }
}

function _setSpecialistSidebarCollapsed(collapsed, { persist = false } = {}) {
  document.querySelectorAll('.specialist-group[data-specialist-app]').forEach(root => {
    const group = root.dataset.specialistApp || 'app';
    root.dataset.sidebarCollapsed = collapsed ? 'true' : 'false';
    const toggle = root.querySelector('[data-specialist-sidebar-toggle]');
    toggle?.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    toggle?.setAttribute('aria-label', `${collapsed ? 'show' : 'hide'} ${group} navigation`);
  });
  if (persist) {
    try { window.localStorage.setItem(SPECIALIST_SIDEBAR_STORAGE_KEY, collapsed ? '1' : '0'); }
    catch { /* storage can be unavailable in private or embedded contexts */ }
  }
}

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
  const response = await request(url, options);
  if (!response.ok) {
    let payload = null;
    try { payload = await response.json(); } catch { /* keep the bounded fallback */ }
    const message = payload?.error?.message || payload?.detail?.message || payload?.detail;
    throw new Error(typeof message === 'string' ? message : `request failed: ${response.status}`);
  }
  return response.json();
}

function _list(title, rows, emptyCopy) {
  const section = _el('section', 'specialist-group-card');
  section.append(_el('h2', '', title));
  const list = _el('div', 'specialist-group-list');
  if (!rows.length) list.append(_el('p', 'specialist-group-empty', emptyCopy));
  for (const row of rows.slice(0, 6)) {
    const item = _el('div', 'specialist-group-row');
    item.append(_el('strong', '', row.title || 'untitled'));
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
    `partial data: ${unavailable.map(([source, error]) => `${source} unavailable: ${error}`).join('; ')}`,
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
    rows.push({
      id: `event:${item.id || when}:${item.title || ''}`,
      type: 'event',
      title: item.title || 'untitled event',
      date: _dateKey(when),
      time: _timeKey(when),
      meta: item.location || item.calendar || 'calendar',
      sort: _commitmentSortKey(when),
    });
  }
  for (const item of tasks || []) {
    const terminal = String(item.stage || item.status || '').trim().toLowerCase();
    if (item.done === true || ['done', 'completed', 'cancelled', 'canceled'].includes(terminal)) continue;
    const when = String(item.due_date || item.due_at || '');
    rows.push({
      id: `task:${item.id || item.title || ''}`,
      type: 'task',
      title: item.title || 'untitled task',
      date: _dateKey(when),
      time: _timeKey(when),
      meta: item.project_name || item.status || 'task',
      sort: _commitmentSortKey(when),
    });
  }
  for (const item of reminders || []) {
    const when = String(item.trigger_at || item.date || '');
    rows.push({
      id: `reminder:${item.id || when}:${item.text || ''}`,
      type: 'reminder',
      title: item.text || item.title || 'untitled reminder',
      date: _dateKey(when),
      time: _timeKey(when),
      meta: item.repeat_rule || 'reminder',
      sort: _commitmentSortKey(when),
    });
  }
  return rows.sort((left, right) => left.sort.localeCompare(right.sort) || left.title.localeCompare(right.title));
}

function _agendaRows(target, rows, emptyCopy) {
  target.replaceChildren();
  if (!rows.length) {
    target.append(_el('p', 'specialist-workbench-empty', emptyCopy));
    return;
  }
  for (const row of rows) {
    const item = _el('div', 'specialist-record-row');
    item.append(
      _el('span', 'specialist-record-time', row.time || row.date || '--'),
      _el('strong', 'specialist-record-title', row.title),
      _el('span', 'specialist-record-meta', `${row.type} · ${row.meta || row.date || ''}`),
    );
    target.append(item);
  }
}

async function _renderPlan(target, request, section = 'overview') {
  disposePlanBoard();
  if (section === 'board') {
    return renderPlanBoard(target, request, () => _refresh('plan'));
  }
  const [eventsResult, tasksResult, remindersResult] = await Promise.allSettled([
    _json(request, '/api/calendar/agenda?days=8'),
    _json(request, '/api/tasks'),
    _json(request, '/api/reminders'),
  ]);
  const agendaPayload = _settled(eventsResult, {});
  const events = _asArray(agendaPayload, 'days').flatMap(day => _asArray(day, 'events'));
  const tasks = _asArray(_settled(tasksResult, []));
  const reminders = _asArray(_settled(remindersResult, []));
  const failures = [
    ['calendar', _settledError(eventsResult, 'calendar data could not be loaded')],
    ['tasks', _settledError(tasksResult, 'task data could not be loaded')],
    ['reminders', _settledError(remindersResult, 'reminder data could not be loaded')],
  ];
  const unavailableSources = failures.filter(([, error]) => error).map(([source]) => source);
  const commitmentsEmpty = unavailableSources.length
    ? `no commitments from available sources · ${unavailableSources.join(', ')} unavailable`
    : 'nothing is committed in this window';
  const unscheduledEmpty = failures[1][1]
    ? 'tasks unavailable · unscheduled work could not be checked'
    : 'no unscheduled tasks';
  const commitments = planCommitments(events, tasks, reminders);
  target.replaceChildren();

  const capture = _el('form', 'specialist-group-capture');
  capture.setAttribute('aria-label', 'quick task');
  const input = _el('input');
  input.type = 'text';
  input.name = 'title';
  input.maxLength = 500;
  input.placeholder = 'capture a task';
  input.autocomplete = 'off';
  const button = _el('button', '', 'add task');
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
        captureMessage.textContent = error?.message || 'task could not be added';
        captureMessage.hidden = false;
        input.focus();
        return;
      }
      input.value = '';
      try {
        await _refresh('plan');
      } catch (error) {
        captureMessage.textContent = `task saved; plan could not refresh: ${error?.message || 'refresh failed'}`;
        captureMessage.hidden = false;
      }
    } finally { button.disabled = false; }
  });

  const workbench = _el('div', 'specialist-workbench specialist-workbench-plan');
  const rail = _el('aside', 'specialist-workbench-rail');
  rail.append(_el('h2', '', 'time'));
  const today = _todayKey();
  const sevenDayEndKey = addDateKeyDays(today, 7);
  let windowName = 'today';
  const agenda = _el('section', 'specialist-workbench-main');
  const agendaHead = _el('div', 'specialist-workbench-head');
  agendaHead.append(_el('h2', '', 'ordered commitments'), _el('span', '', today));
  const agendaList = _el('div', 'specialist-record-list');
  const renderWindow = value => {
    windowName = value;
    let rows = commitments;
    let empty = commitmentsEmpty;
    if (value === 'today') rows = commitments.filter(item => item.date === today);
    if (value === 'seven') {
      rows = commitments.filter(item => item.date >= today && item.date < sevenDayEndKey);
    }
    if (value === 'unscheduled') {
      rows = commitments.filter(item => item.type === 'task' && !item.date);
      empty = unscheduledEmpty;
    }
    agendaHead.querySelector('span').textContent = value === 'today' ? today : value === 'seven' ? 'next seven days' : 'no date';
    _agendaRows(agendaList, rows, empty);
  };
  const choices = _choiceButtons('Plan time window', [
    { value: 'today', label: `today · ${commitments.filter(item => item.date === today).length}` },
    { value: 'seven', label: `next 7 days · ${commitments.filter(item => item.date >= today && item.date < sevenDayEndKey).length}` },
    { value: 'unscheduled', label: `unscheduled · ${commitments.filter(item => item.type === 'task' && !item.date).length}` },
  ], windowName, renderWindow);
  rail.append(choices, _el('h2', '', 'specialists'));
  const jumps = _el('div', 'specialist-workbench-jumps');
  jumps.append(
    _sectionJump('plan', 'calendar', 'calendar'),
    _sectionJump('plan', 'tasks', 'tasks'),
    _sectionJump('plan', 'reminders', 'reminders'),
  );
  rail.append(jumps);
  agenda.append(agendaHead, agendaList);
  const aside = _el('aside', 'specialist-workbench-detail');
  aside.append(_el('h2', '', 'quick capture'), capture, _el('h2', '', 'unscheduled'));
  const unscheduled = commitments.filter(item => item.type === 'task' && !item.date);
  const unscheduledList = _el('div', 'specialist-record-list');
  _agendaRows(unscheduledList, unscheduled.slice(0, 6), unscheduledEmpty);
  aside.append(unscheduledList);
  workbench.append(rail, agenda, aside);
  const partial = _partialAvailability(failures);
  if (partial) target.append(partial);
  target.append(workbench);
  renderWindow(section === 'week' ? 'seven' : 'today');
}

async function _renderInbox(target, request) {
  const [accountsResult, contactsResult] = await Promise.allSettled([
    _json(request, '/api/mail/accounts'),
    _json(request, '/api/contacts'),
  ]);
  const accounts = _asArray(_settled(accountsResult, []));
  const contacts = _asArray(_settled(contactsResult, []));
  const accountsError = _settledError(accountsResult, 'mail accounts could not be loaded');
  const contactsError = _settledError(contactsResult, 'contacts could not be loaded');
  const cached = await Promise.allSettled(accounts.map(account =>
    _json(request, `/api/mail/cached/${encodeURIComponent(account.id)}?folder=INBOX&limit=24`)));
  const cachedFailures = cached.flatMap((result, index) => result.status === 'rejected'
    ? [[`cached mail for ${accounts[index]?.name || accounts[index]?.email || 'account'}`, result.reason?.message || 'messages could not be loaded']]
    : []);
  const failures = [
    ['mail accounts', accountsError],
    ['contacts', contactsError],
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
  rail.append(_el('h2', '', 'mailboxes'));
  const main = _el('section', 'specialist-workbench-main');
  const head = _el('div', 'specialist-workbench-head');
  head.append(_el('h2', '', 'cached messages'), _sectionJump('inbox', 'mail', 'open mail', 'specialist-inline-action'));
  const messageList = _el('div', 'specialist-message-list');
  const detail = _el('aside', 'specialist-workbench-detail');
  let selectedAccount = '';
  let selectedMessage = null;
  const emptyMailboxCopy = accountsError
    ? 'mail accounts unavailable'
    : cachedFailures.length
      ? 'cached mail is unavailable for one or more accounts; no messages were returned by available accounts'
      : accounts.length ? 'cached inbox is clear' : 'connect an account in Mail';
  const sender = message => message.from_name || message.from || message.sender || message.from_email || '';
  const drawDetail = message => {
    detail.replaceChildren();
    detail.append(_el('h2', '', 'selected message'));
    if (!message) {
      detail.append(_el('p', 'specialist-workbench-empty', emptyMailboxCopy));
      return;
    }
    detail.append(
      _el('strong', 'specialist-detail-title', message.subject || '(no subject)'),
      _el('p', 'specialist-detail-meta', `${sender(message) || 'unknown sender'} · ${_dateLabel(message.date || message.received_at || message.internal_date)}`),
      _el('p', 'specialist-detail-body', message.snippet || message.preview || message.body_text || 'Open Mail to read the full cached message.'),
    );
    const contact = contacts.find(item => {
      const address = mailboxAddress(message.from_email || message.from || '');
      return address && mailboxAddress(item.email) === address;
    });
    detail.append(_el('h2', '', 'person context'));
    if (contact) {
      detail.append(
        _el('strong', 'specialist-detail-title', contact.name || contact.email),
        _el('p', 'specialist-detail-meta', contact.email || contact.phone || ''),
        _sectionJump('inbox', 'contacts', 'open contact', 'specialist-inline-action'),
      );
    } else {
      detail.append(_el('p', 'specialist-workbench-empty', contactsError ? 'contacts unavailable' : 'no matching contact record'));
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
        _el('strong', 'specialist-record-title', message.subject || '(no subject)'),
        _el('span', 'specialist-record-meta', sender(message) || message.account_name || 'unknown sender'),
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
  const mailboxChoices = [{ value: '', label: `all accounts · ${messages.length}` }, ...accounts.map(account => ({
    value: String(account.id ?? ''),
    label: `${account.name || account.email || 'account'} · ${messages.filter(item => item.account_id === String(account.id ?? '')).length}`,
  }))];
  rail.append(_choiceButtons('Inbox account', mailboxChoices, selectedAccount, value => {
    selectedAccount = value;
    drawMessages();
  }), _el('h2', '', 'people'));
  const people = _el('div', 'specialist-workbench-jumps');
  people.append(_sectionJump('inbox', 'contacts', `all contacts · ${contacts.length}`));
  rail.append(people);
  main.append(head, messageList);
  workbench.append(rail, main, detail);
  const partial = _partialAvailability(failures);
  if (partial) target.append(partial);
  target.append(workbench);
  drawMessages();
}

async function _renderLibrary(target, request) {
  const [readResult, booksResult] = await Promise.allSettled([
    _json(request, '/api/read'),
    _json(request, '/api/books/overview'),
  ]);
  const read = _asArray(_settled(readResult, {}), 'items');
  const booksData = _settled(booksResult, {});
  const readError = _settledError(readResult, 'saved reading could not be loaded');
  const booksError = _settledError(booksResult, 'books could not be loaded');
  const shelves = booksData?.shelves || {};
  const books = [
    ..._asArray(shelves.reading).map(item => ({ ...item, reading_state: 'reading' })),
    ..._asArray(shelves.want).map(item => ({ ...item, reading_state: 'want' })),
    ..._asArray(shelves.done).map(item => ({ ...item, reading_state: 'done' })),
  ];
  const records = [
    ...read.map(item => ({
      id: `saved:${item.id || item.url || item.title}`,
      kind: item.source === 'andromeda_news' ? 'saved news' : 'saved reading',
      title: item.title || item.url || 'untitled saved item',
      meta: item.site || item.url || item.status || 'saved',
      section: 'read',
      state: item.status || (item.read ? 'read' : 'unread'),
    })),
    ...books.map(item => ({
      id: `book:${item.id || item.title}`,
      kind: 'book',
      title: item.title || 'untitled book',
      meta: item.author || item.reading_state || 'book',
      section: 'books',
      state: item.reading_state,
    })),
  ];
  target.replaceChildren();
  const note = _el('p', 'specialist-group-note', 'news enters Library only when you choose save. feeds and existing read-later items keep their current behavior.');
  const workbench = _el('div', 'specialist-workbench specialist-workbench-library');
  const rail = _el('aside', 'specialist-workbench-rail');
  rail.append(_el('h2', '', 'material'));
  const main = _el('section', 'specialist-workbench-main');
  const head = _el('div', 'specialist-workbench-head');
  head.append(_el('h2', '', 'reading queue'), _el('span', '', `${records.length} items`));
  const list = _el('div', 'specialist-message-list');
  let filter = 'all';
  const draw = () => {
    list.replaceChildren();
    const visible = records.filter(item => filter === 'all' || (filter === 'saved' ? item.section === 'read' : item.section === 'books'));
    head.querySelector('span').textContent = `${visible.length} item${visible.length === 1 ? '' : 's'}`;
    if (!visible.length) {
      const unavailable = filter === 'saved' ? (readError ? 'saved reading' : '')
        : filter === 'books' ? (booksError ? 'books' : '')
          : [readError && 'saved reading', booksError && 'books'].filter(Boolean).join(' and ');
      list.append(_el(
        'p',
        'specialist-workbench-empty',
        unavailable ? `${unavailable} unavailable; no items were returned by available sources` : 'nothing in this part of Library yet',
      ));
      return;
    }
    for (const record of visible) {
      const button = _sectionJump('library', record.section, '', 'specialist-library-row');
      button.setAttribute('aria-label', `open ${record.kind}: ${record.title}`);
      button.append(
        _el('span', 'specialist-record-time', record.kind),
        _el('strong', 'specialist-record-title', record.title),
        _el('span', 'specialist-record-meta', `${record.state || 'saved'} · ${record.meta}`),
      );
      list.append(button);
    }
  };
  rail.append(_choiceButtons('Library material', [
    { value: 'all', label: `everything · ${records.length}` },
    { value: 'saved', label: `saved · ${read.length}` },
    { value: 'books', label: `books · ${books.length}` },
  ], filter, value => { filter = value; draw(); }), _el('h2', '', 'specialists'));
  const jumps = _el('div', 'specialist-workbench-jumps');
  jumps.append(_sectionJump('library', 'read', 'saved reading'), _sectionJump('library', 'books', 'books'));
  rail.append(jumps);
  main.append(head, list);
  const detail = _el('aside', 'specialist-workbench-detail');
  detail.append(
    _el('h2', '', 'save boundary'),
    _el('p', 'specialist-detail-body', 'A News item appears here only after you choose Save to Library. Browsing a feed never creates a record.'),
    _sectionJump('library', 'read', 'open saved reading', 'specialist-inline-action'),
  );
  workbench.append(rail, main, detail);
  target.append(note);
  const partial = _partialAvailability([
    ['saved reading', readError],
    ['books', booksError],
  ]);
  if (partial) target.append(partial);
  target.append(workbench);
  draw();
}

async function _renderHealth(target, request) {
  const [healthResult, habitsResult] = await Promise.allSettled([
    _json(request, '/api/health/overview'),
    _json(request, '/api/habits/overview'),
  ]);
  const health = _asArray(_settled(healthResult, {}), 'kinds');
  const habits = _asArray(_settled(habitsResult, {}), 'habits');
  const healthError = _settledError(healthResult, 'measurements could not be loaded');
  const habitsError = _settledError(habitsResult, 'habits could not be loaded');
  target.replaceChildren();
  const note = _el('p', 'specialist-group-note', 'health records stay local and follow the existing sensitive-context rules.');
  const workbench = _el('div', 'specialist-workbench specialist-workbench-health');
  const rail = _el('aside', 'specialist-workbench-rail');
  rail.append(_el('h2', '', 'today'));
  const rhythm = _el('div', 'specialist-health-rhythm');
  if (!habits.length) rhythm.append(_el('p', 'specialist-workbench-empty', habitsError ? 'habits unavailable' : 'no habits yet'));
  for (const habit of habits) {
    const button = _sectionJump('health', 'habits', '', 'specialist-habit-row');
    button.setAttribute('aria-label', `open habit ${habit.name || 'untitled'}`);
    button.append(
      _el('strong', '', habit.name || 'untitled habit'),
      _el('span', '', habit.done_today ? 'done today' : `${habit.streak || 0} day streak`),
    );
    rhythm.append(button);
  }
  rail.append(rhythm, _el('h2', '', 'specialists'));
  const jumps = _el('div', 'specialist-workbench-jumps');
  jumps.append(_sectionJump('health', 'health', 'health log'), _sectionJump('health', 'habits', 'habits'));
  rail.append(jumps);
  const main = _el('section', 'specialist-workbench-main');
  const head = _el('div', 'specialist-workbench-head');
  head.append(_el('h2', '', 'latest measurements'), _el('span', '', `${health.length} kinds`));
  const measurements = _el('div', 'specialist-record-list');
  if (!health.length) measurements.append(_el('p', 'specialist-workbench-empty', healthError ? 'measurements unavailable' : 'no measurements yet'));
  for (const item of health) {
    const row = _el('div', 'specialist-record-row');
    row.append(
      _el('span', 'specialist-record-time', item.latest?.date || '--'),
      _el('strong', 'specialist-record-title', item.label || item.kind || 'measurement'),
      _el('span', 'specialist-record-meta', item.latest ? `${item.latest.value} ${item.latest.unit || ''}` : 'no entries'),
    );
    measurements.append(row);
  }
  main.append(head, measurements);
  const detail = _el('aside', 'specialist-workbench-detail');
  const completed = habits.filter(item => item.done_today).length;
  detail.append(
    _el('h2', '', 'today rhythm'),
    _el('strong', 'specialist-detail-title', habitsError ? 'habit status unavailable' : `${completed} of ${habits.length} habits complete`),
    _el('p', 'specialist-detail-body', 'Habit completion stays separate from measurement records. A Project selection never grants Aide access to health data.'),
    _sectionJump('health', 'health', 'open health history', 'specialist-inline-action'),
  );
  workbench.append(rail, main, detail);
  target.append(note);
  const partial = _partialAvailability([
    ['measurements', healthError],
    ['habits', habitsError],
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
      title: 'ledger status unavailable',
      detail: 'Finance records remain untouched. Reload after the local status request recovers.',
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
      title: healthy ? 'Actual is canonical' : 'Actual canonical ledger needs attention',
      detail: healthy
        ? 'Transaction writes go only to Actual. The previous Alles ledger is frozen for the release rollback window.'
        : 'Actual is still authoritative, but its managed service is unavailable. Recover the service or return to the frozen Alles ledger.',
      actions: [...recovery, 'rollback-ledger'],
    };
  }
  if (!service.available) {
    return {
      state: 'unavailable',
      title: 'Actual unavailable',
      detail: `Node 22 or newer is required. Detected ${service.node_version || 'no supported Node runtime'}.`,
      actions: [],
    };
  }
  if (!service.installed) {
    return {
      state: 'not-installed',
      title: 'Alles ledger active',
      detail: 'Actual 26.7.0 is not installed. Installation stays inside the Alles data directory and binds only to loopback.',
      actions: ['install'],
    };
  }
  if (!service.healthy) {
    return {
      state: service.running ? 'unhealthy' : 'stopped',
      title: service.running ? 'Actual needs attention' : 'Actual stopped',
      detail: 'The current Finance authority is unchanged. Start the managed service before staging or using the canonical ledger.',
      actions: [service.running ? 'restart' : 'start'],
    };
  }
  const runStatus = ledger.run?.status || '';
  if (runStatus === 'ready') {
    return {
      state: 'ready',
      title: 'staging parity passed',
      detail: 'The staged Actual budget matches the current Alles snapshot. A fresh check and cold backup run again at cutover.',
      actions: ['cutover', 'backup', 'stop'],
    };
  }
  if (runStatus === 'staging') {
    return {
      state: 'staging',
      title: 'staging in progress',
      detail: 'Alles remains authoritative while the isolated Actual copy is built and reconciled.',
      actions: ['backup'],
    };
  }
  return {
    state: runStatus === 'failed' ? 'failed' : 'available',
    title: runStatus === 'failed' ? 'staging needs a fresh run' : 'Actual ready to stage',
    detail: runStatus === 'failed'
      ? (ledger.run?.error || 'The last staging run failed. Alles stayed authoritative and can be staged again.')
      : 'Alles is authoritative. Staging copies the ledger into Actual without switching writes.',
    actions: [
      ...(/^[A-Z]{3}$/.test(String(ledger.base_currency_code || '').trim()) ? ['stage'] : []),
      'backup',
      'stop',
    ],
  };
}

const ACTUAL_ACTION_LABELS = Object.freeze({
  install: 'install Actual 26.7.0',
  start: 'start Actual',
  restart: 'restart Actual',
  stop: 'stop Actual',
  backup: 'create cold backup',
  stage: 'stage and reconcile',
  cutover: 'review cutover',
  'rollback-ledger': 'review ledger rollback',
});

function _actualConfirmation(panel, action, trigger, runAction) {
  panel.querySelector('.finance-actual-confirm')?.remove();
  const confirmation = _el('section', 'finance-actual-confirm');
  confirmation.setAttribute('role', 'region');
  confirmation.setAttribute('aria-label', action === 'cutover' ? 'confirm Actual cutover' : 'confirm ledger rollback');
  confirmation.tabIndex = -1;
  const heading = _el('h3', '', action === 'cutover' ? 'switch transaction authority?' : 'return to the frozen Alles ledger?');
  const body = _el('p', '', action === 'cutover'
    ? 'Alles will recheck parity, create a cold backup, then send transaction writes only to Actual. The old rows stay unchanged and read-only.'
    : 'This restores write authority to the unchanged pre-cutover Alles ledger. Transactions written only to Actual after cutover are not copied back.');
  const actions = _el('div', 'finance-actual-confirm-actions');
  const cancel = _el('button', '', 'keep current authority');
  cancel.type = 'button';
  const confirm = _el('button', 'finance-actual-confirm-primary', action === 'cutover' ? 'switch writes to Actual' : 'restore Alles authority');
  confirm.type = 'button';
  const close = () => {
    confirmation.remove();
    trigger.focus();
  };
  cancel.addEventListener('click', close);
  confirm.addEventListener('click', () => {
    confirmation.remove();
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
  panel.setAttribute('aria-label', 'Actual ledger status');
  const heading = _el('header', 'finance-actual-head');
  heading.append(_el('h2', '', 'Actual ledger'), _el('strong', '', presentation.title));
  const detail = _el('p', 'finance-actual-detail', presentation.detail);
  const facts = _el('dl', 'finance-actual-facts');
  const fact = (term, description) => {
    facts.append(_el('dt', '', term), _el('dd', '', description));
  };
  fact('authority', reported ? (ledger.mode === 'actual' ? 'Actual' : 'Alles') : 'not reported');
  fact('base currency', ledger.base_currency_code || 'not reported');
  fact('managed service', reported ? (service.installed ? `${service.version || '26.7.0'} · ${service.healthy ? 'healthy' : service.running ? 'unhealthy' : 'stopped'}` : 'not installed') : 'status unavailable');
  if (ledger.run) fact('latest parity run', `${ledger.run.status || 'unknown'} · ${ledger.run.links ?? 0} mapped records`);
  const message = _el('p', 'finance-actual-message');
  message.setAttribute('role', 'status');
  message.setAttribute('aria-live', 'polite');
  const actions = _el('div', 'finance-actual-actions');

  const setBusy = busy => {
    actions.querySelectorAll('button').forEach(button => { button.disabled = busy; });
  };
  const runAction = async (action, returnFocus = null) => {
    setBusy(true);
    panel.querySelector('.finance-actual-confirm')?.remove();
    message.classList.remove('finance-actual-error');
    message.textContent = `${ACTUAL_ACTION_LABELS[action]} in progress…`;
    let url = `/api/finance/actual/service/${action}`;
    const options = { method: 'POST' };
    if (action === 'stage') {
      const baseCurrency = String(ledger.base_currency_code || '').trim();
      if (!/^[A-Z]{3}$/.test(baseCurrency)) {
        message.textContent = 'A reviewed base currency is required before staging';
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
        message.textContent = `cold backup ${result.backup_id || ''} verified`;
        setBusy(false);
      } else {
        await _refresh('finance');
      }
    } catch (error) {
      message.textContent = error?.message || 'Actual action failed';
      message.classList.add('finance-actual-error');
      setBusy(false);
      if (returnFocus?.isConnected) returnFocus.focus();
    }
  };

  for (const action of presentation.actions) {
    const button = _el('button', action === 'cutover' ? 'finance-actual-primary' : '', ACTUAL_ACTION_LABELS[action]);
    button.type = 'button';
    button.dataset.actualAction = action;
    button.addEventListener('click', () => {
      if (action === 'cutover' || action === 'rollback-ledger') {
        _actualConfirmation(panel, action, button, runAction);
      } else {
        runAction(action);
      }
    });
    actions.append(button);
  }
  panel.append(heading, detail, facts, actions, message);
  return panel;
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
  const accountsError = _settledError(accountsResult, 'account data could not be loaded');
  const subscriptionsError = _settledError(subscriptionsResult, 'subscription data could not be loaded');
  const actualError = _settledError(actualResult, 'Actual status could not be loaded');
  target.replaceChildren();
  const note = _el('p', 'specialist-group-note', 'balances remain in their original currency. converted totals show their rate evidence when available.');
  const grid = _el('div', 'specialist-group-grid specialist-group-grid-two');
  grid.append(
    _list('accounts', accounts.map(item => ({ title: item.name, meta: `${item.currency_code || item.currency || ''} ${item.balance ?? 0}`.trim() })), accountsError ? `accounts unavailable: ${accountsError}` : 'no accounts yet'),
    _list('subscriptions', subscriptions.map(item => ({ title: item.name, meta: `${item.currency || ''}${item.price ?? 0} · ${item.cycle || ''}` })), subscriptionsError ? `subscriptions unavailable: ${subscriptionsError}` : 'no subscriptions yet'),
  );
  target.append(note, _renderActualStatus(actual, request));
  if (actualError) target.append(_el('p', 'specialist-group-error', `Actual status unavailable: ${actualError}`));
  target.append(grid);
}

async function _renderServer(target, request, section) {
  const module = await import('./server_workbench.js?v=4');
  return module.renderServerSection(target, request, section);
}

function _choiceField(label, options, selected, onSelect) {
  const field = _el('fieldset', 'finance-import-choice');
  field.append(_el('legend', '', label));
  const list = _el('div', 'finance-import-choice-list');
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', label);
  const buttons = options.map(option => {
    const button = _el('button', '', option.label);
    button.type = 'button';
    button.setAttribute('role', 'option');
    button.dataset.value = option.value;
    const active = option.value === selected;
    button.setAttribute('aria-selected', active ? 'true' : 'false');
    button.tabIndex = active ? 0 : -1;
    button.addEventListener('click', () => {
      buttons.forEach(item => {
        const chosen = item === button;
        item.setAttribute('aria-selected', chosen ? 'true' : 'false');
        item.tabIndex = chosen ? 0 : -1;
      });
      onSelect(option.value);
    });
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const current = buttons.indexOf(button);
      const backwards = ['ArrowLeft', 'ArrowUp'].includes(event.key);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
        : (current + (backwards ? -1 : 1) + buttons.length) % buttons.length;
      buttons[next].focus();
      buttons[next].click();
    });
    list.append(button);
    return button;
  });
  field.append(list);
  return field;
}

function _renderImportReceipt(target, receipt, request, refresh) {
  target.replaceChildren();
  if (!receipt) {
    target.append(_el('p', 'specialist-group-empty', 'choose an account, reviewed profile, and statement file to preview. nothing posts before review.'));
    return;
  }
  const heading = _el('div', 'finance-import-receipt-head');
  const message = _el('p', 'finance-import-message');
  message.setAttribute('role', 'status');
  message.setAttribute('aria-live', 'polite');
  heading.append(
    _el('strong', '', receipt.source_name),
    _el('span', '', `${receipt.counts.rows} rows · ${receipt.counts.pending} ready · ${receipt.counts.duplicates} duplicate · ${receipt.counts.conflicts} review`),
  );
  const rows = _el('div', 'finance-import-rows');
  for (const row of receipt.rows) {
    const parsed = row.parsed || {};
    const item = _el('div', `finance-import-row finance-import-row-${row.status}`);
    item.append(
      _el('span', 'finance-import-row-date', parsed.date || `line ${row.row_number}`),
      _el('strong', '', parsed.payee || row.conflict_reason || 'needs review'),
      _el('span', 'finance-import-row-amount', parsed.amount_text ? `${parsed.currency_code} ${parsed.amount_text}` : ''),
      _el('span', 'finance-import-row-status', row.status.replace('_', ' ')),
    );
    if (row.conflict_reason && parsed.payee) item.append(_el('small', '', row.conflict_reason));
    if (row.status === 'needs_review' && /conversion evidence/i.test(row.conflict_reason || '')) {
      const form = _el('form', 'finance-import-conversion');
      const baseCode = receipt.canonical_base_currency_code || 'base';
      const baseAmount = _el('input');
      baseAmount.name = 'base_amount_text';
      baseAmount.inputMode = 'decimal';
      baseAmount.placeholder = `${baseCode} amount`;
      baseAmount.setAttribute('aria-label', `${baseCode} converted amount`);
      const rate = _el('input');
      rate.name = 'rate_text';
      rate.inputMode = 'decimal';
      rate.placeholder = `${baseCode} per ${parsed.currency_code || 'source unit'}`;
      rate.setAttribute('aria-label', `conversion rate in ${baseCode} per ${parsed.currency_code || 'source unit'}`);
      const rateDate = _el('input');
      rateDate.name = 'rate_date';
      rateDate.type = 'date';
      rateDate.setAttribute('aria-label', 'conversion rate date');
      const source = _el('input');
      source.name = 'source';
      source.placeholder = 'rate source';
      source.setAttribute('aria-label', 'conversion rate source');
      const save = _el('button', '', 'save reviewed conversion');
      save.type = 'submit';
      form.append(baseAmount, rate, rateDate, source, save);
      form.addEventListener('submit', async event => {
        event.preventDefault();
        save.disabled = true;
        message.textContent = '';
        try {
          const body = Object.fromEntries(new FormData(form));
          await refresh(await _json(
            request,
            `/api/finance/imports/${encodeURIComponent(receipt.id)}/rows/${encodeURIComponent(row.id)}/conversion`,
            { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) },
          ));
        } catch (error) {
          message.textContent = error?.message || 'conversion evidence could not be saved';
        } finally { save.disabled = false; }
      });
      item.append(form);
    }
    if (row.status === 'needs_review' && /confirm account ending/i.test(row.conflict_reason || '')) {
      const confirm = _el(
        'button',
        'finance-import-confirm-account',
        `confirm ending ${parsed.account_suffix || ''} belongs to ${receipt.receipt?.account_name || 'this account'}`,
      );
      confirm.type = 'button';
      confirm.addEventListener('click', async () => {
        confirm.disabled = true;
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
        } catch (error) {
          message.textContent = error?.message || 'account suffix could not be confirmed';
        } finally { confirm.disabled = false; }
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
        resolutionButtons.forEach(button => { button.disabled = true; });
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
        } catch (error) {
          message.textContent = error?.message || 'match decision could not be saved';
        } finally {
          resolutionBusy = false;
          resolutionButtons.forEach(button => { button.disabled = false; });
        }
      };
      const duplicate = _el('button', '', 'treat as duplicate');
      duplicate.type = 'button';
      duplicate.addEventListener('click', () => resolve('duplicate'));
      const importNew = _el('button', '', 'import as new');
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
        recoveryButtons.forEach(button => { button.disabled = true; });
        message.textContent = '';
        try {
          if (decision === 'delete'
            && !await confirmDialog('delete the edited Actual transaction, then return this row to the import queue?')) return;
          await refresh(await _json(
            request,
            `/api/finance/imports/${encodeURIComponent(receipt.id)}/rows/${encodeURIComponent(row.id)}/resolve-recovery`,
            {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ decision }),
            },
          ));
        } catch (error) {
          message.textContent = error?.message || 'interrupted import could not be recovered';
        } finally {
          recoveryBusy = false;
          recoveryButtons.forEach(button => { button.disabled = false; });
        }
      };
      const keep = _el('button', '', 'accept edited Actual transaction as replacement');
      keep.type = 'button';
      keep.addEventListener('click', () => resolve('keep'));
      const retry = _el('button', '', 'delete it and retry');
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
  const mutateReceipt = async (path, failureMessage) => {
    if (receiptMutationBusy) return;
    receiptMutationBusy = true;
    receiptMutationButtons.forEach(button => { button.disabled = true; });
    message.textContent = '';
    try {
      await refresh(await _json(request, path, { method: 'POST' }));
    } catch (error) {
      message.textContent = error?.message || failureMessage;
    } finally {
      receiptMutationBusy = false;
      receiptMutationButtons.forEach(button => { button.disabled = false; });
    }
  };
  const canFinishDuplicates = receipt.counts.rows > 0 && receipt.counts.duplicates === receipt.counts.rows;
  if (receipt.status === 'preview' && (receipt.counts.pending > 0 || canFinishDuplicates) && receipt.counts.conflicts === 0 && receipt.counts.applying === 0) {
    const label = receipt.counts.pending > 0
      ? `apply ${receipt.counts.pending} ready row${receipt.counts.pending === 1 ? '' : 's'}`
      : 'finish duplicate receipt';
    const apply = _el('button', 'finance-import-apply', label);
    apply.type = 'button';
    apply.addEventListener('click', () => mutateReceipt(
      `/api/finance/imports/${encodeURIComponent(receipt.id)}/apply`,
      'import could not be applied',
    ));
    receiptMutationButtons.push(apply);
    actions.append(apply);
  }
  const unresolvedClaim = receipt.rows.some(row => row.status === 'applying'
    || (row.status === 'conflict' && row.created_transaction_id));
  if (['applied', 'preview'].includes(receipt.status) && receipt.counts.applied > 0 && !unresolvedClaim) {
    const undo = _el(
      'button',
      'finance-import-undo',
      receipt.status === 'applied' ? 'undo this import' : 'undo applied rows',
    );
    undo.type = 'button';
    undo.addEventListener('click', () => mutateReceipt(
      `/api/finance/imports/${encodeURIComponent(receipt.id)}/undo`,
      'import could not be undone',
    ));
    receiptMutationButtons.push(undo);
    actions.append(undo);
  }
  target.append(heading, rows, actions, message);
}

async function _renderImports(target, request) {
  target.replaceChildren(_el('p', 'specialist-group-empty', 'loading reviewed import profiles…'));
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
      `import setup unavailable: ${error?.message || 'request failed'}`,
    );
    const retry = _el('button', '', 'retry import setup');
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
    target.append(_el('p', 'specialist-group-empty', 'create a Finance account before importing a statement.'));
    return;
  }
  const profiles = Array.isArray(profileData?.profiles) ? profileData.profiles : [];
  if (!profiles.length) {
    target.append(_el('p', 'specialist-group-empty', 'no reviewed import profiles are available. Nothing was uploaded or changed.'));
    return;
  }
  let accountId = accounts[0].id;
  let profileId = profiles[0].id;
  let selectedFile = null;
  let previewGeneration = 0;
  let activePreviewGeneration = 0;
  const panel = _el('section', 'finance-import-panel');
  const boundary = _el('p', 'specialist-group-note', 'reviewed files only. Alles never asks for a CIBC or China Merchants Bank password, and no direct provider is enabled.');
  const choices = _el('div', 'finance-import-choices');
  choices.append(
    _choiceField('account', accounts.map(account => ({ value: account.id, label: `${account.name} · ${account.currency_code || account.currency}` })), accountId, value => {
      accountId = value;
      previewGeneration += 1;
    }),
    _choiceField('profile', profiles.map(profile => ({ value: profile.id, label: profile.label })), profileId, value => {
      profileId = value;
      previewGeneration += 1;
    }),
  );
  const fileInput = _el('input');
  fileInput.type = 'file';
  fileInput.accept = '.csv,.txt,text/csv,text/plain';
  fileInput.hidden = true;
  const fileRow = _el('div', 'finance-import-file-row');
  const choose = _el('button', '', 'choose statement or notification file');
  choose.type = 'button';
  const fileName = _el('span', '', 'no file chosen');
  const preview = _el('button', 'finance-import-preview', 'preview import');
  preview.type = 'button';
  preview.disabled = true;
  const previewMessage = _el('p', 'finance-import-message');
  previewMessage.setAttribute('role', 'status');
  previewMessage.setAttribute('aria-live', 'polite');
  choose.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    previewGeneration += 1;
    selectedFile = fileInput.files?.[0] || null;
    fileName.textContent = selectedFile?.name || 'no file chosen';
    preview.disabled = !selectedFile;
  });
  const receiptTarget = _el('section', 'finance-import-receipt');
  let historyTarget;
  const showReceipt = async receipt => {
    _renderImportReceipt(receiptTarget, receipt, request, showReceipt);
    try {
      const history = await _json(request, '/api/finance/imports');
      historyTarget.replaceChildren(...history.map(item => {
        const button = _el('button', '', `${item.source_name} · ${item.status}`);
        button.type = 'button';
        button.addEventListener('click', () => showReceipt(item));
        return button;
      }));
    } catch {
      historyTarget.replaceChildren(_el(
        'p',
        'specialist-group-empty',
        'recent receipts could not be refreshed; the receipt above is current.',
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
    preview.disabled = true;
    choose.disabled = true;
    choiceButtons.forEach(button => { button.disabled = true; });
    previewMessage.textContent = '';
    try {
      if (file.size > 5 * 1024 * 1024) {
        throw new Error('statement files must be 5 MiB or smaller');
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
        previewMessage.textContent = error?.message || 'import preview could not be created';
      }
    } finally {
      if (activePreviewGeneration === generation) {
        preview.disabled = !selectedFile;
        choose.disabled = false;
        choiceButtons.forEach(button => { button.disabled = false; });
        activePreviewGeneration = 0;
      }
    }
  });
  fileRow.append(fileInput, choose, fileName, preview, previewMessage);
  const historySection = _el('section', 'finance-import-history');
  historySection.append(_el('h2', '', 'recent receipts'));
  historyTarget = _el('div', 'finance-import-history-list');
  historySection.append(historyTarget);
  panel.append(boundary, choices, fileRow, receiptTarget, historySection);
  target.append(panel);
  _renderImportReceipt(receiptTarget, receipts[0] || null, request, showReceipt);
  if (historyUnavailable) {
    historyTarget.replaceChildren(_el('p', 'specialist-group-empty', 'recent receipts are unavailable; new imports still work.'));
  } else {
    historyTarget.replaceChildren(...receipts.map(item => {
      const button = _el('button', '', `${item.source_name} · ${item.status}`);
      button.type = 'button';
      button.addEventListener('click', () => showReceipt(item));
      return button;
    }));
  }
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
  activeTab?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
}

function _wire(group, root) {
  if (root.dataset.groupWired) return;
  root.dataset.groupWired = '1';
  root.querySelectorAll('[data-group-section]').forEach(button => {
    button.addEventListener('click', () => window._navigateSpecialistSection?.(group, button.dataset.groupSection));
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const tabs = [...root.querySelectorAll('[data-group-section]')];
      const current = tabs.indexOf(button);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
        : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].focus();
      tabs[next].click();
    });
  });
  _setSpecialistSidebarCollapsed(_storedSidebarCollapsed());
  root.querySelector('[data-specialist-sidebar-toggle]')?.addEventListener('click', () => {
    _setSpecialistSidebarCollapsed(root.dataset.sidebarCollapsed !== 'true', { persist: true });
  });
  root.querySelector('[data-files-back]')?.addEventListener('click', () => window._navigateSpecialistSection?.('files', 'files'));
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
  _setTabs(root, selected);
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
    overview.replaceChildren(_el('p', 'specialist-group-empty', 'loading current data…'));
    return _renderCurrentOverview(group, selected, overview, request, renderNonce);
  }

  overview.hidden = true;
  slot.hidden = false;
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

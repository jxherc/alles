import { calendarDateKey, chosenTimeZone, formatCalendarDate, formatClock, formatDate, formatDateParts, formatDateTime, t, tp } from './i18n.js';
import { autosizeTextarea, wireAutosizeTextarea } from './text_entry.js?v=1';
import { appDesc, appLabel, toast } from './util.js';
import { appGlyph } from './icons.js';

const SECTION_LABELS = {
  needs_you: 'needs you',
  today: 'schedule',
  in_progress: 'in progress',
  briefs: 'briefs',
  shortcuts: 'pinned apps',
};
const SHORTCUT_ALIASES = { calendar: 'plan', tasks: 'plan', days: 'plan', reminders: 'plan', mail: 'inbox', contacts: 'inbox', notes: 'wiki', journal: 'wiki', photos: 'files', gallery: 'files', books: 'library', read: 'library', habits: 'health', money: 'finance', subs: 'finance', secrets: 'vault', server: 'system', watch: 'system', activity: 'system' };
const SUGGESTION_LINKS = new Set(['tasks', 'calendar', 'reminders', 'subs', 'days', 'habits', 'read', 'books', 'health', 'money', 'mail', 'journal', 'contacts', 'home']);

const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

let navigate = () => {};
let openRecord = null;
let askAide = async () => false;
let legacyShortcuts = () => null;
let legacyChecked = false;
let apps = [];
let data = null;
let preferences = null;
let suggestions = [];
let clockTimer = null;
let headingPeriod = '';
let headingGreeting = '';
let statusTimer = null;
let statusGeneration = 0;
let loadGeneration = 0;

const HOME_GREETINGS = {
  night: ['home.greeting.night.1', 'home.greeting.night.2', 'home.greeting.night.3'],
  morning: ['home.greeting.morning.1', 'home.greeting.morning.2', 'home.greeting.morning.3'],
  afternoon: ['home.greeting.afternoon.1', 'home.greeting.afternoon.2', 'home.greeting.afternoon.3'],
  evening: ['home.greeting.evening.1', 'home.greeting.evening.2', 'home.greeting.evening.3'],
};

export function homeGreetingFor(date = new Date(), random = Math.random) {
  const hour = Number(formatDateParts(date, {
    hour: 'numeric', hourCycle: 'h23', numberingSystem: 'latn',
  })
    .find(part => part.type === 'hour')?.value || 0);
  const period = hour < 5 ? 'night' : hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening';
  const pool = HOME_GREETINGS[period];
  const index = Math.min(pool.length - 1, Math.floor(Math.max(0, Number(random()) || 0) * pool.length));
  return { period, text: t(pool[index]) };
}

// today's reminders read as a time. one left over from an earlier day says which day too: the
// full text the reminders list uses goes to aide and the tooltip, and the narrow time column gets
// it on two lines, day over time (the year only when it isn't this one)
function reminderRow(item, date) {
  const row = { view: 'reminders', id: item.id, meta: formatClock(item.at), title: item.text, kind: 'reminder' };
  const day = String(item.trigger_at || '').slice(0, 10);
  if (!day || !date || day === date) return row;
  const short = day.slice(0, 4) === date.slice(0, 4) ? { month: 'short', day: 'numeric' } : { dateStyle: 'short' };
  return {
    ...row,
    meta: formatDateTime(item.trigger_at, { dateStyle: 'medium', timeStyle: 'short' }),
    lines: [formatCalendarDate(day, short), row.meta],
  };
}

export function dailyRows(day) {
  const rows = [];
  for (const item of day?.events || []) rows.push({ view: 'calendar', id: item.id, occurrence: day.date, meta: item.time ? formatClock(item.time) : t('home.all_day'), title: item.title, kind: 'event' });
  for (const item of day?.tasks?.overdue || []) rows.push({ view: 'tasks', id: item.id, meta: t('home.overdue'), title: item.title, urgent: true, kind: 'task' });
  for (const item of day?.tasks?.due_today || []) rows.push({ view: 'tasks', id: item.id, meta: t('common.today'), title: item.title, kind: 'task' });
  for (const item of day?.reminders || []) rows.push(reminderRow(item, day.date));
  for (const item of day?.renewing || []) rows.push({ view: 'subs', id: item.id, meta: item.in_days ? t('home.in_days', { count: item.in_days }) : t('common.today'), title: `${item.name} ${t('home.renews')}`, kind: 'renewal' });
  for (const item of day?.day_events || []) rows.push({ view: 'days', id: item.id, meta: item.in_days ? t('home.in_days', { count: item.in_days }) : t('common.today'), title: item.name, kind: 'date' });
  for (const item of day?.habits || []) rows.push({ view: 'habits', id: item.id, meta: t('home.not_done'), title: item.name, kind: 'habit' });
  return rows;
}

// anything tied to today (events, reminders, birthdays, renewals, habits) always shows; open tasks
// fill up to 6 and the rest are counted on a row that opens plan, where they live. habits live in
// health, so they never hide behind it
export function homeScheduleRows(rows, limit = 6) {
  const tasks = rows.filter(item => item.kind === 'task');
  const shown = new Set(tasks.slice(0, limit));
  const out = rows.filter(item => item.kind !== 'task' || shown.has(item));
  const hidden = tasks.length - shown.size;
  if (hidden) out.push({ view: 'plan', id: '', meta: '', title: tp('home.more_in_plan', hidden), kind: 'more' });
  return out;
}

export function homeDayRequest(sections) {
  const attention = (sections?.needs_you || []).slice(0, 5)
    .map(item => `needs attention: ${item.title}${item.summary ? ` — ${item.summary}` : ''}`);
  const dated = dailyRows(sections?.today).slice(0, 20).map(item => `${item.kind}: ${item.meta} — ${item.title}`);
  const lines = [...attention, ...dated]
    .map(line => String(line).replace(/\s+/g, ' ').trim().slice(0, 350));
  return `here's the day context available in alles:\n${lines.join('\n') || 'no dated items are showing.'}\n\nplease give me a short rundown: what matters first, what can wait, and anything i might miss.`;
}

export function homeAidePreview(value, limit = 180) {
  const plain = String(value || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)/gm, ' ')
    .replace(/[*_~`>#]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (plain.length <= limit) return plain;
  const clipped = plain.slice(0, limit + 1);
  const boundary = clipped.lastIndexOf(' ');
  return `${clipped.slice(0, boundary > limit * 0.65 ? boundary : limit).trim()}…`;
}

export function normalizeTodayPreferences(value, appViews = []) {
  const keys = Object.keys(SECTION_LABELS);
  const raw = value && typeof value === 'object' ? value : {};
  const order = [...new Set(Array.isArray(raw.order) ? raw.order.filter(key => keys.includes(key)) : [])];
  for (const key of keys) if (!order.includes(key)) order.push(key);
  const visible = new Set(Array.isArray(raw.visible) ? raw.visible.filter(key => keys.includes(key)) : keys);
  visible.add('needs_you');
  const allowedApps = new Set(appViews);
  const hasSavedShortcuts = Array.isArray(raw.shortcuts);
  const shortcuts = [...new Set(hasSavedShortcuts ? raw.shortcuts
    .map(view => String(view || '').trim().toLowerCase())
    .map(view => SHORTCUT_ALIASES[view] || view)
    .filter(view => allowedApps.has(view)) : [])];
  return {
    order,
    visible: [...visible],
    density: raw.density === 'compact' ? 'compact' : 'comfortable',
    shortcuts: hasSavedShortcuts ? shortcuts : ['plan', 'wiki', 'files'].filter(view => allowedApps.has(view)),
  };
}

export function orderedVisibleHomeSections(value) {
  const visible = new Set(value?.visible || []);
  visible.add('needs_you');
  return (value?.order || Object.keys(SECTION_LABELS)).filter(key => visible.has(key));
}

function dayRow(item, extra = '') {
  return `<button class="today-row${item.urgent ? ' urgent' : ''}" type="button" data-view="${esc(item.view)}" data-record="${esc(item.id || '')}" data-occurrence="${esc(item.occurrence || '')}">
    <span><b>${esc(item.title)}</b>${extra}</span>${item.lines ? `<em title="${esc(item.meta)}">${item.lines.map(esc).join('<br>')}</em>` : `<em>${esc(item.meta)}</em>`}
  </button>`;
}

function attentionRow(item) {
  const summary = item.summary ? `<small>${esc(item.summary)}</small>` : '';
  const meta = [item.project, item.state].filter(Boolean).join(' · ');
  return `<button class="today-row${item.state === 'uncertain' || item.state === 'failed' ? ' urgent' : ''}" type="button" data-run="${esc(item.run_id || '')}">
    <span><b>${esc(item.title)}</b>${summary}</span><em>${esc(meta)}</em>
  </button>`;
}

function section(key, title, meta, body, className = '') {
  return `<section class="today-section ${className}" data-home-section="${esc(key)}">
    <header><h2>${esc(title)}</h2><span>${esc(meta)}</span></header>
    <div class="today-list">${body}</div>
  </section>`;
}

function briefRow(item) {
  const text = homeAidePreview(item?.summary || item?.title || t('home.brief_ready'));
  const isNews = item?.kind === 'news';
  return `<button class="today-brief" type="button" data-view="${isNews ? 'scheduled' : 'chat'}"${isNews ? ' data-aide-section="news"' : ''}><span>${isNews ? t('home.news') : t('home.brief_aide')}</span><p>${esc(text)}</p></button>`;
}

function shortcutRows() {
  const byView = new Map(apps.map(item => [item.view, item]));
  const selected = (preferences?.shortcuts || []).map(view => byView.get(view)).filter(Boolean);
  if (!selected.length) return `<p class="today-empty">${esc(t('home.no_pinned_apps'))}</p>`;
  return `<div class="today-shortcuts">${selected.map(item => `<button class="today-shortcut" type="button" data-view="${esc(item.view)}"><span class="today-shortcut-glyph">${appGlyph(item.view)}</span><b>${esc(appLabel(item.name))}</b><small>${esc(appDesc(item.desc))}</small></button>`).join('')}</div>`;
}

function pinnedAppsSection() {
  return `<section class="today-section today-shortcut-section" data-home-section="shortcuts">
    <header><h2>${esc(t('home.pinned_apps'))}</h2><button class="today-section-edit" id="today-pinned-apps-edit" type="button" data-home-pinned-edit aria-label="${esc(t('home.edit_pinned_apps'))}">${esc(t('common.edit'))}</button></header>
    <div class="today-list">${shortcutRows()}</div>
  </section>`;
}

function suggestionSection() {
  if (!suggestions.length) return '';
  const rows = suggestions.map(item => {
    const title = esc(item.title);
    const body = item.body ? `<small>${esc(item.body)}</small>` : '';
    const content = `<b>${title}</b>${body}`;
    const open = SUGGESTION_LINKS.has(item.link)
      ? `<button class="today-suggestion-open" type="button" data-suggestion-act="${esc(item.id)}" aria-label="${esc(t('home.open_named', { title: item.title }))}">${content}</button>`
      : `<div class="today-suggestion-text">${content}</div>`;
    return `<div class="today-suggestion">${open}
      <button class="today-suggestion-dismiss" type="button" data-suggestion-dismiss="${esc(item.id)}" aria-label="${esc(t('home.dismiss_named', { title: item.title }))}">${esc(t('common.dismiss'))}</button>
      <small class="today-suggestion-status" role="status" hidden></small>
    </div>`;
  }).join('');
  return `<section class="today-section today-suggestions" aria-label="${esc(t('home.suggestions'))}">
    <header><h2>${esc(t('home.suggestions'))}</h2></header><div class="today-list">${rows}</div>
  </section>`;
}

async function useSuggestion(button, action) {
  const row = button.closest('.today-suggestion');
  const id = button.dataset.suggestionAct || button.dataset.suggestionDismiss;
  const item = suggestions.find(card => card.id === id);
  if (!row || !item) return;
  const index = suggestions.indexOf(item);
  const controls = row.querySelectorAll('button');
  controls.forEach(control => { control.disabled = true; });
  try {
    const result = await json(`/api/proactive/${encodeURIComponent(id)}/${action}`, { method: 'POST' });
    if (result?.ok !== true) throw new Error('unconfirmed suggestion');
  } catch {
    const status = row.querySelector('.today-suggestion-status');
    if (status) {
      status.textContent = t('home.suggestion_unconfirmed');
      status.hidden = false;
    }
    controls.forEach(control => { control.disabled = false; });
    return;
  }
  suggestions = suggestions.filter(card => card.id !== id);
  render();
  if (document.getElementById('today-view')?.style.display === 'none') return;
  if (action === 'act') {
    try { await navigate(item.link); }
    catch { showStatus(t('home.suggestion_open_failed')); }
  } else {
    const remaining = document.querySelectorAll('.today-suggestion-dismiss');
    (remaining[Math.min(index, remaining.length - 1)] || document.getElementById('today-settings'))?.focus();
  }
}

function render() {
  const root = document.getElementById('today-sections');
  if (!root || !data) return;

  const day = data.today || {};
  const dayItems = homeScheduleRows(dailyRows(day));
  const needs = data.needs_you || [];
  const running = data.in_progress || [];
  const briefs = data.briefs || [];
  const openTasks = day.tasks?.open_count;

  const blocks = {
    needs_you: section(
      'needs_you',
      t('home.needs_you'),
      needs.length || '',
      needs.slice(0, 5).map(attentionRow).join('') || `<p class="today-empty">${esc(t('home.nothing_needs_attention'))}</p>`,
      'today-needs',
    ),
    today: section(
      'today',
      t('home.schedule'),
      '',
      dayItems.map(item => dayRow(item, item.kind === 'event' ? `<small>${esc(t('calendar.title'))}</small>` : '')).join('') || `<p class="today-empty">${esc(t('home.nothing_scheduled'))}</p>`,
      'today-schedule',
    ),
    in_progress: section(
      'in_progress',
      t('home.in_progress'),
      running.length || '',
      running.slice(0, 5).map(attentionRow).join('') || `<p class="today-empty">${esc(t('home.no_aide_running'))}</p>`,
      'today-progress',
    ),
    briefs: section(
      'briefs',
      t('home.briefs'),
      briefs.length || '',
      briefs.slice(0, 3).map(briefRow).join('') || `<p class="today-empty">${esc(t('home.no_briefs'))}</p>`,
      'today-briefs',
    ),
    shortcuts: pinnedAppsSection(),
  };

  root.classList.toggle('compact', preferences?.density === 'compact');
  root.innerHTML = orderedVisibleHomeSections(preferences)
    .filter(key => (key !== 'in_progress' || running.length) && (key !== 'briefs' || briefs.length))
    .map(key => blocks[key]).filter(Boolean).join('') + suggestionSection();
  root.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', async () => {
    if (button.dataset.record && openRecord) {
      await openRecord(button.dataset.view, button.dataset.record, button.dataset.occurrence);
      return;
    }
    await navigate(button.dataset.view);
    if (button.dataset.aideSection) {
      const module = await import('./aidescheduled.js?v=248');
      await module.activateAideScheduledTab(button.dataset.aideSection);
    }
  }));
  root.querySelectorAll('[data-run]').forEach(button => button.addEventListener('click', () => openRecord?.('chat', button.dataset.run)));
  root.querySelector('[data-home-pinned-edit]')?.addEventListener('click', () => {
    document.getElementById('today-settings')?.click();
  });
  root.querySelectorAll('[data-suggestion-act]').forEach(button => button.addEventListener('click', () => useSuggestion(button, 'act')));
  root.querySelectorAll('[data-suggestion-dismiss]').forEach(button => button.addEventListener('click', () => useSuggestion(button, 'dismiss')));

  const summary = document.getElementById('today-summary');
  if (summary) {
    const taskLabel = Number.isInteger(openTasks) ? tp('home.open_count', openTasks) : t('tasks.title');
    summary.innerHTML = `${esc(tp('home.attention_count', needs.length))} <button type="button" class="today-summary-tasks">${esc(taskLabel)}</button>`;
    summary.querySelector('button').addEventListener('click', () => navigate('tasks', { allTasks: true }));
  }
}

function showStatus(message, temporary = false) {
  const status = document.getElementById('today-status');
  if (!status) return;
  if (statusTimer) clearTimeout(statusTimer);
  statusTimer = null;
  const generation = ++statusGeneration;
  status.hidden = false;
  status.textContent = message;
  if (temporary) {
    statusTimer = setTimeout(() => {
      if (generation === statusGeneration) status.hidden = true;
    }, 1600);
  }
}

function hideStatus() {
  if (statusTimer) clearTimeout(statusTimer);
  statusTimer = null;
  statusGeneration += 1;
  const status = document.getElementById('today-status');
  if (status) status.hidden = true;
}

async function load() {
  const generation = ++loadGeneration;
  const recovery = document.getElementById('today-capture-recovery');
  if (recovery) import('./capture.js').then(({ showPendingCapture }) => showPendingCapture(recovery, homeCaptureSaved)).catch(() => {
    recovery.textContent = t('home.capture_recovery_failed');
  });
  void loadNoteRecovery();
  showStatus(t('home.loading'));
  try {
    const date = calendarDateKey();
    // only a zone the browser really reports; the server remembers it for reminders
    const timezone = encodeURIComponent(chosenTimeZone());
    const todayResponse = await fetch(`/api/today?date=${date}&timezone=${timezone}`);
    if (generation !== loadGeneration) return false;
    if (!todayResponse.ok) throw new Error(t('home.unavailable'));
    const today = await todayResponse.json();
    if (generation !== loadGeneration) return false;
    data = today.sections;
    let savedPreferences = {};
    let preferencesPartial = false;
    try {
      let oldShortcuts = null;
      if (!legacyChecked) {
        try { oldShortcuts = legacyShortcuts(); }
        catch { preferencesPartial = true; }
      }
      const preferenceResponse = oldShortcuts === null
        ? await fetch('/api/today/preferences')
        : await fetch('/api/today/preferences/import-legacy', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ shortcuts: oldShortcuts }),
        });
      if (generation !== loadGeneration) return false;
      if (!preferenceResponse.ok) throw new Error('preferences unavailable');
      const preferenceValue = await preferenceResponse.json();
      savedPreferences = oldShortcuts === null ? preferenceValue : preferenceValue.preferences;
      if (oldShortcuts !== null) legacyChecked = true;
      if (generation !== loadGeneration) return false;
    } catch {
      if (generation !== loadGeneration) return false;
      preferencesPartial = true;
    }
    preferences = normalizeTodayPreferences(savedPreferences, apps.map(item => item.view));
    if (!data) throw new Error(t('home.not_enabled'));
    let suggestionsPartial = false;
    try {
      const cards = await json('/api/proactive');
      if (generation !== loadGeneration) return false;
      if (!Array.isArray(cards)) throw new Error('suggestions unavailable');
      suggestions = cards.filter(item => typeof item?.id === 'string' && typeof item.title === 'string').slice(0, 4);
    } catch {
      if (generation !== loadGeneration) return false;
      suggestions = [];
      suggestionsPartial = true;
    }
    if (generation !== loadGeneration) return false;
    render();
    const partial = [...(today.partial_sources || []), ...(preferencesPartial ? [t('home.source_customization')] : []), ...(suggestionsPartial ? [t('home.suggestions')] : [])];
    if (partial.length) {
      showStatus(t('home.partial_sources', { sources: partial.join(', ').replaceAll('_', ' ') }));
      return false;
    }
    hideStatus();
    return true;
  } catch {
    if (generation !== loadGeneration) return false;
    const status = document.getElementById('today-status');
    if (status) {
      showStatus(t('home.load_error'));
      status.innerHTML = `${esc(t('home.load_error'))} <button class="btn" id="today-retry" type="button">${esc(t('common.retry'))}</button>`;
      document.getElementById('today-retry')?.addEventListener('click', load);
    }
    return false;
  }
}

function safeTitle(value) {
  let title = String(value || '').trim().split('\n')[0].replace(/^#+\s*/, '').replace(/^[-*]\s+(\[[ xX]\]\s+)?/, '').trim();
  title = title.replace(/[\\/:*?"<>|#\[\]]+/g, ' ').replace(/\s+/g, ' ').trim();
  const characters = [...title];
  if (characters.length > 60) title = characters.slice(0, 60).join('').replace(/\s+\S*$/, '').trim();
  return title || 'note';
}

async function json(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { 'content-type': 'application/json', ...(options.headers || {}) },
    body: options.body && typeof options.body !== 'string' ? JSON.stringify(options.body) : options.body,
  });
  if (!response.ok) {
    // a 400 says why ("feb 30 isn't a date"); anything else stays generic
    const detail = response.status === 400 ? (await response.json().catch(() => ({})))?.detail : '';
    throw new Error(typeof detail === 'string' && detail ? detail : t('common.request_failed'));
  }
  return response.json();
}

async function openCapturedNote(path) {
  return window._openSearchResult?.('note', path);
}

async function loadNoteRecovery() {
  const host = document.getElementById('today-note-recovery');
  if (!host) return;
  try {
    const { showNoteRecovery } = await import('./note_capture.js');
    await showNoteRecovery(host, homeNoteSaved, openCapturedNote);
  } catch { host.textContent = t('home.note_recovery_failed'); }
}

function homeNoteSaved(saved, text, focus = false) {
  const input = document.getElementById('today-capture-input');
  const asTask = document.getElementById('today-capture-mode')?.getAttribute('aria-pressed') === 'true';
  if (input && !asTask && input.value === text) {
    input.value = '';
    autosizeTextarea(input);
  }
  const host = document.getElementById('today-note-recovery');
  if (host) {
    host.dataset.savedNoteRequest = saved.request_id;
    const status = document.createElement('p'); status.textContent = t('home.note_saved'); status.setAttribute('role', 'status');
    const open = document.createElement('button'); open.type = 'button'; open.className = 'btn note-saved-open'; open.textContent = t('home.open_note');
    open.onclick = () => openCapturedNote(saved.path).catch(() => toast(t('home.open_note_failed'), 'error'));
    host.replaceChildren(status, open);
    if (focus && input?.getClientRects().length) open.focus();
    // on wide screens "note saved · open note" floats, so it goes after a while unless you're
    // on it. on a phone it sits in the page; hiding it would pull the page up under the finger
    clearTimeout(homeNoteSaved.timer);
    if (window.matchMedia?.('(min-width: 761px)').matches) homeNoteSaved.timer = setTimeout(function clear() {
      if (host.contains(document.activeElement)) { homeNoteSaved.timer = setTimeout(clear, 4000); return; }
      if (host.dataset.savedNoteRequest === saved.request_id) host.replaceChildren();
    }, 8000);
  } else toast(t('home.note_saved'), 'success');
  if (input?.getClientRects().length) void load();
}

function homeCaptureSaved(saved, kind) {
  const input = document.getElementById('today-capture-input');
  const asTask = document.getElementById('today-capture-mode')?.getAttribute('aria-pressed') === 'true';
  if (input && asTask && kind === 'task' && saved.source?.kind === 'capture' && input.value === saved.source.excerpt) {
    input.value = '';
    autosizeTextarea(input);
  }
  if (input?.getClientRects().length) void load();
}

function wireCapture() {
  const form = document.getElementById('today-capture');
  const mode = document.getElementById('today-capture-mode');
  const input = document.getElementById('today-capture-input');
  if (!form || form.dataset.wired) return;
  form.dataset.wired = '1';
  wireAutosizeTextarea(input);
  input.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    form.requestSubmit();
  });
  mode.addEventListener('click', () => {
    const task = mode.getAttribute('aria-pressed') === 'true';
    mode.setAttribute('aria-pressed', String(!task));
    mode.textContent = task ? t('home.note') : t('home.task');
    input.setAttribute('aria-label', task ? t('home.capture_note') : t('home.capture_task'));
    input.focus();
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (form.getAttribute('aria-busy') === 'true') return;
    const value = input.value;
    if (!value.trim()) return;
    const asTask = mode.getAttribute('aria-pressed') === 'true';
    let reviewed = false;
    form.setAttribute('aria-busy', 'true');
    input.disabled = true;
    mode.disabled = true;
    const submit = form.querySelector('[type="submit"]');
    if (submit) submit.disabled = true;
    try {
      if (asTask) {
        if ([...value].length > 6000) throw new Error(t('home.capture_too_long'));
        const proposal = await json('/api/tasks/quick', { method: 'POST', body: { text: value, preview: true, today: calendarDateKey() } });
        if (proposal?.preview !== true || proposal.kind !== 'task' || !proposal.candidate?.title || proposal.source?.excerpt !== value) throw new Error(t('home.task_preview_unconfirmed'));
        const { openCaptureReview } = await import('./capture.js');
        reviewed = await openCaptureReview(proposal, submit, homeCaptureSaved);
      } else {
        const { saveNote } = await import('./note_capture.js');
        const result = await saveNote(value, safeTitle(value));
        homeNoteSaved(result, value);
      }
    } catch (error) {
      showStatus(asTask ? t('home.prepare_task_failed', { reason: error.message }) : t('home.note_unconfirmed', { reason: error.message }));
      if (!asTask) await loadNoteRecovery();
    }
    finally {
      form.removeAttribute('aria-busy');
      input.disabled = false;
      mode.disabled = false;
      if (submit) submit.disabled = false;
      if (!reviewed && input.getClientRects().length) input.focus();
    }
  });
}

function updateHeading() {
  const now = new Date();
  const next = homeGreetingFor(now);
  if (next.period !== headingPeriod) {
    headingPeriod = next.period;
    headingGreeting = next.text;
  }
  const name = (localStorage.getItem('alles-name') || '').trim();
  const heading = document.getElementById('today-greeting');
  if (heading) heading.textContent = name ? `${headingGreeting}, ${name}` : headingGreeting;
  const date = document.getElementById('today-date');
  if (date) date.textContent = formatDate(now, { weekday: 'long', month: 'long', day: 'numeric' }).toLowerCase();
  const clock = document.getElementById('today-clock');
  if (clock) {
    if (!clock.querySelector('.today-clock-hour')) {
      // minutes are enough; a ticking second pulled the eye every time
      clock.innerHTML = '<span class="today-clock-date"></span> <span class="today-clock-hour"></span><span class="today-clock-colon">:</span><span class="today-clock-minute"></span> <span class="today-clock-period"></span>';
    }
    const parts = Object.fromEntries(formatDateParts(now, {
      hour: 'numeric', minute: '2-digit',
    }).map(part => [part.type, part.value]));
    clock.querySelector('.today-clock-date').textContent = formatDate(now, { weekday: 'short', month: 'short', day: 'numeric' }).toLowerCase();
    clock.querySelector('.today-clock-hour').textContent = parts.hour || '';
    clock.querySelector('.today-clock-minute').textContent = parts.minute || '';
    clock.querySelector('.today-clock-period').textContent = (parts.dayPeriod || '').toLowerCase();
  }
}

function wireHome() {
  document.getElementById('today-ask-aide')?.addEventListener('click', async () => {
    if (!data?.today) { showStatus(t('home.load_error')); return; }
    await askAide(homeDayRequest(data));
  });
  document.querySelectorAll('[data-today-destination]').forEach(button => button.addEventListener('click', () => {
    if (button.dataset.todayDestination === 'apps') document.getElementById('app-drawer-btn')?.click();
    else navigate(button.dataset.todayDestination);
  }));
  window.addEventListener('alles:home-preferences-changed', event => {
    preferences = normalizeTodayPreferences(event.detail, apps.map(item => item.view));
    render();
  });
  window.addEventListener('alles:localization-change', () => {
    headingPeriod = '';
    updateHeading();
    render();
  });
  wireCapture();
}

export function initToday(options) {
  navigate = options.navigate;
  openRecord = options.openRecord || null;
  askAide = options.askAide;
  apps = options.apps;
  legacyShortcuts = options.legacyShortcuts || (() => null);
  const root = document.getElementById('today-view');
  if (root && !root.dataset.wired) {
    root.dataset.wired = '1';
    wireHome();
  }
  updateHeading();
  if (!clockTimer) clockTimer = setInterval(updateHeading, 1_000);
  load();
}

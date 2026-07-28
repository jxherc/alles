import { calendarDateKey, formatDate, formatDateParts, t, tp } from './i18n.js';
import { toast } from './util.js';

const SECTION_LABELS = {
  needs_you: 'needs you',
  today: 'schedule',
  in_progress: 'in progress',
  briefs: 'briefs',
  shortcuts: 'pinned apps',
};
const SHORTCUT_ALIASES = { calendar: 'plan', tasks: 'plan', days: 'plan', reminders: 'plan', mail: 'inbox', contacts: 'inbox', notes: 'wiki', journal: 'wiki', photos: 'files', gallery: 'files', books: 'library', read: 'library', habits: 'health', money: 'finance', subs: 'finance', secrets: 'vault', server: 'system', watch: 'system', activity: 'system' };

const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

let navigate = () => {};
let apps = [];
let data = null;
let preferences = null;
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

export function dailyRows(day) {
  const rows = [];
  for (const item of day?.events || []) rows.push({ view: 'calendar', meta: item.time || t('home.all_day'), title: item.title, kind: 'event' });
  for (const item of day?.tasks?.overdue || []) rows.push({ view: 'tasks', meta: t('home.overdue'), title: item.title, urgent: true, kind: 'task' });
  for (const item of day?.tasks?.due_today || []) rows.push({ view: 'tasks', meta: t('common.today'), title: item.title, kind: 'task' });
  for (const item of day?.reminders || []) rows.push({ view: 'reminders', meta: item.at, title: item.text, kind: 'reminder' });
  for (const item of day?.renewing || []) rows.push({ view: 'subs', meta: item.in_days ? t('home.in_days', { count: item.in_days }) : t('common.today'), title: `${item.name} ${t('home.renews')}`, kind: 'renewal' });
  for (const item of day?.day_events || []) rows.push({ view: 'days', meta: item.in_days ? t('home.in_days', { count: item.in_days }) : t('common.today'), title: item.name, kind: 'date' });
  for (const item of day?.habits || []) rows.push({ view: 'habits', meta: t('home.not_done'), title: item.name, kind: 'habit' });
  return rows.slice(0, 12);
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
  return `<button class="today-row${item.urgent ? ' urgent' : ''}" type="button" data-view="${esc(item.view)}">
    <span><b>${esc(item.title)}</b>${extra}</span><em>${esc(item.meta)}</em>
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
  return `<button class="today-brief" type="button" data-view="${isNews ? 'scheduled' : 'chat'}"${isNews ? ' data-aide-section="news"' : ''}><span>${isNews ? 'news' : 'aide'}</span><p>${esc(text)}</p></button>`;
}

function shortcutRows() {
  const byView = new Map(apps.map(item => [item.view, item]));
  const selected = (preferences?.shortcuts || []).map(view => byView.get(view)).filter(Boolean);
  if (!selected.length) return `<p class="today-empty">${esc(t('home.no_pinned_apps'))}</p>`;
  return `<div class="today-shortcuts">${selected.map(item => `<button class="today-shortcut" type="button" data-view="${esc(item.view)}"><b>${esc(item.name)}</b><small>${esc(item.desc)}</small></button>`).join('')}</div>`;
}

function pinnedAppsSection() {
  return `<section class="today-section today-shortcut-section" data-home-section="shortcuts">
    <header><h2>${esc(t('home.pinned_apps'))}</h2><button class="today-section-edit" id="today-pinned-apps-edit" type="button" data-home-pinned-edit aria-label="${esc(t('home.edit_pinned_apps'))}">${esc(t('common.edit'))}</button></header>
    <div class="today-list">${shortcutRows()}</div>
  </section>`;
}

function render() {
  const root = document.getElementById('today-sections');
  if (!root || !data) return;

  const day = data.today || {};
  const allRows = dailyRows(day);
  const schedule = allRows.filter(item => item.kind === 'event');
  const focus = allRows.filter(item => item.kind !== 'event');
  const needs = data.needs_you || [];
  const running = data.in_progress || [];
  const briefs = data.briefs || [];
  const openTasks = day.tasks?.open_count ?? focus.filter(item => item.kind === 'task').length;

  const dayItems = [...schedule, ...focus.slice(0, 8)];
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
      tp('home.open_count', openTasks),
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
  root.innerHTML = orderedVisibleHomeSections(preferences).map(key => blocks[key]).filter(Boolean).join('');
  root.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', async () => {
    await navigate(button.dataset.view);
    if (button.dataset.aideSection) {
      const module = await import('./aidescheduled.js?v=246');
      await module.activateAideScheduledTab(button.dataset.aideSection);
    }
  }));
  root.querySelectorAll('[data-run]').forEach(button => button.addEventListener('click', () => navigate('chat')));
  root.querySelector('[data-home-pinned-edit]')?.addEventListener('click', () => {
    document.getElementById('today-settings')?.click();
  });

  const summary = document.getElementById('today-summary');
  if (summary) {
    summary.textContent = `${tp('home.attention_count', needs.length)} ${tp('home.priority_count', openTasks)} ${t('home.summary_tail')}`;
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
  showStatus(t('home.loading'));
  try {
    const date = calendarDateKey();
    const todayResponse = await fetch(`/api/today?date=${date}`);
    if (generation !== loadGeneration) return false;
    if (!todayResponse.ok) throw new Error(t('home.unavailable'));
    const today = await todayResponse.json();
    if (generation !== loadGeneration) return false;
    data = today.sections;
    let savedPreferences = {};
    let preferencesPartial = false;
    try {
      const preferenceResponse = await fetch('/api/today/preferences');
      if (generation !== loadGeneration) return false;
      if (!preferenceResponse.ok) throw new Error('preferences unavailable');
      savedPreferences = await preferenceResponse.json();
      if (generation !== loadGeneration) return false;
    } catch {
      if (generation !== loadGeneration) return false;
      preferencesPartial = true;
    }
    preferences = normalizeTodayPreferences(savedPreferences, apps.map(item => item.view));
    if (!data) throw new Error(t('home.not_enabled'));
    if (generation !== loadGeneration) return false;
    render();
    const partial = [...(today.partial_sources || []), ...(preferencesPartial ? ['customization'] : [])];
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
  if (title.length > 60) title = title.slice(0, 60).replace(/\s+\S*$/, '').trim();
  return title || 'note';
}

async function json(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { 'content-type': 'application/json', ...(options.headers || {}) },
    body: options.body && typeof options.body !== 'string' ? JSON.stringify(options.body) : options.body,
  });
  if (!response.ok) throw new Error('request failed');
  return response.json();
}

async function capture(text, asTask) {
  if (asTask) return json('/api/tasks', { method: 'POST', body: { title: text } });
  const title = safeTitle(text);
  return json('/api/vault-md/file', {
    method: 'POST',
    body: { path: title, content: `${text.trim()}\n`, unique: true },
  });
}

function wireCapture() {
  const form = document.getElementById('today-capture');
  const mode = document.getElementById('today-capture-mode');
  const input = document.getElementById('today-capture-input');
  if (!form || form.dataset.wired) return;
  form.dataset.wired = '1';
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
    const value = input.value.trim();
    if (!value) return;
    const asTask = mode.getAttribute('aria-pressed') === 'true';
    form.setAttribute('aria-busy', 'true');
    input.disabled = true;
    mode.disabled = true;
    const submit = form.querySelector('[type="submit"]');
    if (submit) submit.disabled = true;
    try {
      await capture(value, asTask);
      input.value = '';
      toast(asTask ? t('home.task_added') : t('home.note_saved'), 'success');
      await load();
    } catch { showStatus(t('home.capture_failed'), true); }
    finally {
      form.removeAttribute('aria-busy');
      input.disabled = false;
      mode.disabled = false;
      if (submit) submit.disabled = false;
      input.focus();
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
      clock.innerHTML = '<span class="today-clock-date"></span> <span class="today-clock-hour"></span><span class="today-clock-colon">:</span><span class="today-clock-minute"></span><span class="today-clock-colon">:</span><span class="today-clock-second"></span> <span class="today-clock-period"></span>';
    }
    const parts = Object.fromEntries(formatDateParts(now, {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    }).map(part => [part.type, part.value]));
    clock.querySelector('.today-clock-date').textContent = formatDate(now, { weekday: 'short', month: 'short', day: 'numeric' }).toLowerCase();
    clock.querySelector('.today-clock-hour').textContent = parts.hour || '';
    clock.querySelector('.today-clock-minute').textContent = parts.minute || '';
    clock.querySelector('.today-clock-second').textContent = parts.second || '';
    clock.querySelector('.today-clock-period').textContent = (parts.dayPeriod || '').toLowerCase();
  }
}

function wireHome() {
  document.getElementById('today-ask-aide')?.addEventListener('click', () => navigate('chat'));
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
  apps = options.apps;
  const root = document.getElementById('today-view');
  if (root && !root.dataset.wired) {
    root.dataset.wired = '1';
    wireHome();
  }
  updateHeading();
  if (!clockTimer) clockTimer = setInterval(updateHeading, 1_000);
  load();
}

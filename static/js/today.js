const SECTION_LABELS = {
  needs_you: 'needs you',
  today: 'today',
  in_progress: 'in progress',
  briefs: 'briefs',
  shortcuts: 'shortcuts',
};
const SECTION_EMPTY = {
  needs_you: 'nothing needs your attention',
  today: 'nothing scheduled — your day is clear',
  in_progress: 'nothing is running',
  briefs: 'finished reports will stay here',
  shortcuts: 'choose shortcuts in customize today',
};

const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

let navigate = () => {};
let apps = [];
let data = null;
let preferences = null;

export function dailyRows(day) {
  const rows = [];
  for (const item of day?.events || []) rows.push({ view: 'calendar', meta: item.time || 'all day', title: item.title });
  for (const item of day?.tasks?.overdue || []) rows.push({ view: 'tasks', meta: 'overdue', title: item.title, urgent: true });
  for (const item of day?.tasks?.due_today || []) rows.push({ view: 'tasks', meta: 'due today', title: item.title });
  for (const item of day?.reminders || []) rows.push({ view: 'reminders', meta: item.at, title: item.text });
  for (const item of day?.renewing || []) rows.push({ view: 'subs', meta: item.in_days ? `in ${item.in_days}d` : 'today', title: `${item.name} renews` });
  for (const item of day?.day_events || []) rows.push({ view: 'days', meta: item.in_days ? `in ${item.in_days}d` : 'today', title: item.name });
  for (const item of day?.habits || []) rows.push({ view: 'habits', meta: 'not done', title: item.name });
  return rows.slice(0, 12);
}

export function normalizeTodayPreferences(value, appViews = []) {
  const keys = Object.keys(SECTION_LABELS);
  const raw = value && typeof value === 'object' ? value : {};
  const order = [...new Set(Array.isArray(raw.order) ? raw.order.filter(key => keys.includes(key)) : [])];
  for (const key of keys) if (!order.includes(key)) order.push(key);
  const visible = new Set(Array.isArray(raw.visible) ? raw.visible.filter(key => keys.includes(key)) : keys);
  visible.add('needs_you');
  const allowedApps = new Set(appViews);
  const shortcuts = [...new Set(Array.isArray(raw.shortcuts) ? raw.shortcuts.filter(view => allowedApps.has(view)) : [])];
  return {
    order,
    visible: [...visible],
    density: raw.density === 'compact' ? 'compact' : 'comfortable',
    shortcuts: shortcuts.length ? shortcuts : ['calendar', 'tasks', 'wiki', 'files'].filter(view => allowedApps.has(view)),
  };
}

function card(item) {
  const summary = item.summary ? `<small>${esc(item.summary)}</small>` : '';
  const meta = [item.project, item.state].filter(Boolean).join(' · ');
  return `<button class="today-row${item.state === 'uncertain' || item.state === 'failed' ? ' urgent' : ''}" type="button" data-run="${esc(item.run_id || '')}">
    <span><b>${esc(item.title)}</b>${summary}</span><em>${esc(meta)}</em>
  </button>`;
}

function dayCard(item) {
  return `<button class="today-row${item.urgent ? ' urgent' : ''}" type="button" data-view="${esc(item.view)}"><span><b>${esc(item.title)}</b></span><em>${esc(item.meta)}</em></button>`;
}

function shortcutCard(view) {
  const app = apps.find(item => item.view === view);
  if (!app) return '';
  return `<button class="today-shortcut" type="button" data-view="${esc(view)}"><b>${esc(app.name)}</b><small>${esc(app.desc)}</small></button>`;
}

function renderSection(key) {
  let body = '';
  if (key === 'today') body = dailyRows(data?.today).map(dayCard).join('');
  else if (key === 'shortcuts') body = preferences.shortcuts.map(shortcutCard).join('');
  else body = (data?.[key] || []).map(card).join('');
  return `<section class="today-section" data-section="${key}">
    <header><h2>${SECTION_LABELS[key]}</h2><span>${key === 'needs_you' && (data?.needs_you?.length || 0) ? data.needs_you.length : ''}</span></header>
    <div class="${key === 'shortcuts' ? 'today-shortcuts' : 'today-list'}">${body || `<p class="today-empty">${SECTION_EMPTY[key]}</p>`}</div>
  </section>`;
}

function render() {
  const root = document.getElementById('today-sections');
  if (!root || !data || !preferences) return;
  root.classList.toggle('compact', preferences.density === 'compact');
  root.innerHTML = preferences.order.filter(key => preferences.visible.includes(key)).map(renderSection).join('');
  root.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => navigate(button.dataset.view)));
  root.querySelectorAll('[data-run]').forEach(button => button.addEventListener('click', () => navigate('chat')));
}

async function load() {
  const status = document.getElementById('today-status');
  if (status) { status.hidden = false; status.textContent = 'loading today…'; }
  try {
    const local = new Date();
    const date = `${local.getFullYear()}-${String(local.getMonth() + 1).padStart(2, '0')}-${String(local.getDate()).padStart(2, '0')}`;
    const todayResponse = await fetch(`/api/today?date=${date}`);
    if (!todayResponse.ok) throw new Error('today unavailable');
    const today = await todayResponse.json();
    data = today.sections;
    let savedPreferences = {};
    let preferencesPartial = false;
    try {
      const preferenceResponse = await fetch('/api/today/preferences');
      if (!preferenceResponse.ok) throw new Error('preferences unavailable');
      savedPreferences = await preferenceResponse.json();
    } catch { preferencesPartial = true; }
    preferences = normalizeTodayPreferences(savedPreferences, apps.map(item => item.view));
    if (!data) throw new Error('today is not enabled');
    render();
    const partial = [...(today.partial_sources || []), ...(preferencesPartial ? ['customization'] : [])];
    if (status && partial.length) {
      status.hidden = false;
      status.textContent = `some sources are unavailable: ${partial.join(', ').replaceAll('_', ' ')}`;
    } else if (status) status.hidden = true;
  } catch {
    if (status) {
      status.hidden = false;
      status.innerHTML = 'today could not load. <button class="btn" id="today-retry" type="button">try again</button>';
      document.getElementById('today-retry')?.addEventListener('click', load);
    }
  }
}

function customize() {
  if (!preferences) return;
  document.getElementById('today-customize-panel')?.remove();
  const panel = document.createElement('div');
  panel.id = 'today-customize-panel';
  panel.className = 'today-customize-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'true');
  panel.setAttribute('aria-label', 'customize today');
  const toggles = preferences.order.map(key => `<div class="today-order-row" data-section-row="${key}"><label><input type="checkbox" data-section-toggle="${key}" ${preferences.visible.includes(key) ? 'checked' : ''} ${key === 'needs_you' ? 'disabled' : ''}> ${SECTION_LABELS[key]}</label><span><button class="icon-btn" type="button" data-move="up" aria-label="move ${SECTION_LABELS[key]} up">↑</button><button class="icon-btn" type="button" data-move="down" aria-label="move ${SECTION_LABELS[key]} down">↓</button></span></div>`).join('');
  const shortcutToggles = apps.map(app => `<label><input type="checkbox" data-shortcut-toggle="${app.view}" ${preferences.shortcuts.includes(app.view) ? 'checked' : ''}> ${esc(app.name)}</label>`).join('');
  panel.innerHTML = `<div class="today-customize-card"><header><h2>customize today</h2><button class="icon-btn" data-close type="button" aria-label="close">×</button></header>
    <p>needs you always stays visible.</p><div class="today-customize-options">${toggles}</div>
    <label class="today-density">density <select class="settings-input" id="today-density"><option value="comfortable">comfortable</option><option value="compact">compact</option></select></label>
    <h3>shortcuts</h3><div class="today-customize-options shortcuts">${shortcutToggles}</div>
    <button class="btn primary" data-save type="button">save changes</button></div>`;
  document.body.appendChild(panel);
  panel.querySelector('#today-density').value = preferences.density;
  const close = () => panel.remove();
  panel.querySelector('[data-close]').addEventListener('click', close);
  panel.addEventListener('click', event => { if (event.target === panel) close(); });
  panel.querySelectorAll('[data-move]').forEach(button => button.addEventListener('click', () => {
    const row = button.closest('[data-section-row]');
    if (button.dataset.move === 'up' && row.previousElementSibling) row.parentElement.insertBefore(row, row.previousElementSibling);
    if (button.dataset.move === 'down' && row.nextElementSibling) row.parentElement.insertBefore(row.nextElementSibling, row);
  }));
  panel.querySelector('[data-save]').addEventListener('click', async () => {
    const next = {
      order: [...panel.querySelectorAll('[data-section-row]')].map(row => row.dataset.sectionRow),
      visible: [...panel.querySelectorAll('[data-section-toggle]:checked')].map(input => input.dataset.sectionToggle),
      density: panel.querySelector('#today-density').value,
      shortcuts: [...panel.querySelectorAll('[data-shortcut-toggle]:checked')].map(input => input.dataset.shortcutToggle),
    };
    const response = await fetch('/api/today/preferences', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(next) });
    if (!response.ok) return;
    preferences = normalizeTodayPreferences(await response.json(), apps.map(item => item.view));
    render(); close();
  });
  panel.querySelector('[data-close]').focus();
}

export function initToday(options) {
  navigate = options.navigate;
  apps = options.apps;
  const date = document.getElementById('today-date');
  if (date) date.textContent = new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' }).format(new Date()).toLowerCase();
  const button = document.getElementById('today-customize-btn');
  if (button && !button.dataset.wired) { button.dataset.wired = '1'; button.addEventListener('click', customize); }
  load();
}

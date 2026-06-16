import { loadSessions, initSessions, newChat, showWelcome, createSession, renderSidebar, exportActiveSessionMarkdown, getActiveId } from './sessions.js';
import { loadModels, renderModelList, renderSidebarModelList, addEndpoint, getSelected, getCurrentEndpoint, initModelModal } from './models.js';
import { sendMessage, stopStream, hideConnBanner } from './chat.js';
import { toast, closeAllModals, mdToHtml, api } from './util.js';
import { runResearch, setResearchMode, isResearchMode } from './research.js';
import { runDocsQuery, setDocsMode, isDocsMode } from './ragquery.js';
import { loadNotes, newNote } from './notes.js';
import { loadTasks, addTask } from './tasks.js';
import { loadCalendar, newEvent } from './calendar.js';
import { loadGallery, initGalleryUpload } from './gallery.js';
import { initSlash, tryExecuteSlashCommand } from './slash.js';
import { attachFile, initDropZone } from './uploads.js';
import { loadProjects } from './projects.js';
import { openSearch, closeSearch, initSearch } from './search.js';
import { initCompareView, loadCompareModels } from './compare.js';
import { loadVaultView, initVault } from './vault.js';
import { loadContacts, addContact } from './contacts.js';
import { loadFiles, initFiles } from './files.js';
import { loadMail } from './mail.js';
import { loadPhotos, initPhotos } from './photos.js';
import { setBaseDomain, parseHost, appForSub, viewToSub, urlForApp, currentSub, SUBDOMAIN_VIEWS } from './subdomain.js';
import { loadBrainPanel } from './brain.js';
import { openSettings, closeSettings, applyVis } from './settings.js';
import { toggleIncognitoMode, setIncognitoMode, getPermMode, setPermMode, permLabel, getEffort, setEffort } from './modes.js';
import { initPrivacyHandlers } from './privacy.js';
import { loadShortcuts, matchesShortcut } from './shortcuts.js';
import { startReminderPoll, initReminderPanel, loadReminders } from './reminders.js';
import { registerServiceWorker } from './push.js';

window._mdToHtml = mdToHtml;

// ── init ──────────────────────────────────────────────────────────────────────
// single sign-on: log in once at alles and every app subdomain unlocks. cookies
// can't be shared across *.localhost, so an unauthed app silently bounces through
// the apex (which holds the session) to mint its own — even on a direct visit.
let _pendingSso = null;

async function init() {
  const params = new URLSearchParams(location.search);
  // 1. redeem a handoff code if an app/the apex sent us one
  const code = params.get('_auth');
  const hadAuthCode = !!code;
  if (code) {
    await fetch('/api/auth/redeem?code=' + encodeURIComponent(code)).catch(() => {});
    _stripParam('_auth');
  }

  let me = {};
  try { me = await fetch('/api/auth/me').then(r => r.json()); setBaseDomain(me.base_domain); } catch {}

  // 2. apex acting as the SSO broker: an app bounced here (?_sso=app.host) for a session
  const ssoTarget = params.get('_sso');
  if (ssoTarget) {
    if (me.authenticated && _validSsoTarget(ssoTarget)) { _ssoRedirect(ssoTarget); return; }
    if (!me.authenticated) { _pendingSso = _validSsoTarget(ssoTarget) ? ssoTarget : null; _showLoginScreen(); return; }
    _stripParam('_sso');   // authed but a junk target → ignore, continue to the hub
  }

  // 3. not authed here → bounce to the apex ONCE to pick up an existing session
  if (!me.authenticated) {
    if (parseHost().sub && !hadAuthCode) {
      sessionStorage.setItem('alles_sso_tried', '1');
      location.assign(urlForApp('') + '?_sso=' + encodeURIComponent(location.host));
      return;
    }
    sessionStorage.removeItem('alles_sso_tried');
    _showLoginScreen();
    return;
  }
  sessionStorage.removeItem('alles_sso_tried');
  await _boot();
}

function _stripParam(name) {
  const p = new URLSearchParams(location.search);
  p.delete(name);
  const q = p.toString();
  history.replaceState(null, '', location.pathname + (q ? '?' + q : '') + location.hash);
}

// apex → mint a one-time code and send it back to the requesting app subdomain
async function _ssoRedirect(target) {
  try {
    const { code } = await fetch('/api/auth/handoff').then(r => r.json());
    location.assign(location.protocol + '//' + target + '/?_auth=' + encodeURIComponent(code));
  } catch { _stripParam('_sso'); _showLoginScreen(); }
}

// only relay a session to OUR own app subdomains (no open-redirect / token leak)
function _validSsoTarget(target) {
  try {
    const u = new URL(location.protocol + '//' + target);
    if (u.port !== location.port || u.hostname === parseHost().base) return false;
    const base = parseHost().base;
    if (!u.hostname.endsWith('.' + base)) return false;
    return !!SUBDOMAIN_VIEWS[u.hostname.slice(0, -('.' + base).length)];
  } catch { return false; }
}

async function _boot() {
  applyVis();
  _syncAppearance();   // pull theme/accent from the server so it matches across subdomains
  if (localStorage.getItem('aide-sidebar-hidden')) document.body.classList.add('sidebar-hidden');
  await loadModels();
  await loadProjects();
  await initSessions();
  const ta = document.getElementById('composer-ta');
  initSlash(ta);
  const { initMentions } = await import('./mentions.js');
  initMentions(ta);
  initSearch();
  initDropZone();
  initVault();
  import('./runs.js').then(m => m.initRuns()).catch(() => {});
  initPrivacyHandlers();
  startReminderPoll();
  registerServiceWorker();
  bindEvents();
  applySubdomainScope();

  // arrived from another subapp's palette "ask aide / research" → run it once
  const _p = new URLSearchParams(location.search);
  const _ask = _p.get('ask');
  if (_ask) {
    history.replaceState(null, '', location.pathname + location.hash);
    setTimeout(() => window._askInChat(_ask, _p.get('web') === '1'), 350);
  }
}

// configure the SPA for whichever subdomain we're on: apex = the hub; an app
// subdomain boots straight into that app with a sidebar scoped to its views.
function applySubdomainScope() {
  const { sub } = parseHost();
  const app = appForSub(sub);
  const onAide = app.app === 'aide';
  const onHub = app.app === 'alles';
  const onSubApp = !!sub && !onAide;

  document.body.classList.toggle('is-hub', onHub);
  document.body.classList.toggle('is-aide', onAide);
  document.body.classList.toggle('is-subapp', onSubApp);
  document.body.dataset.app = app.app;
  document.title = onHub ? 'alles' : `${app.app} / alles`;
  renderAppCrumb(app.app);

  // chats + composer chrome belong to aide only
  _show('sidebar-toggle-btn', onAide);
  _show('new-chat-btn', onAide);
  document.querySelector('.search-wrap')?.style.setProperty('display', onAide ? '' : 'none');
  _show('session-list', onAide);
  _show('ai-top-controls', onAide);
  // settings is AI-heavy — keep it inside aide, not bleeding onto mail/docs/etc.
  _show('topbar-settings-btn', onAide);
  _show('runs-btn', onAide);   // agent runs only make sense on aide
  // on aide the logo lives in the sidebar's top-left; elsewhere it's the topbar crumb
  _show('app-crumb', !onAide);
  if (!onAide) {
    _show('persona-btn', false);
    _show('session-actions-btn', false);
  }
  // the sidebar only renders on aide now, so show every nav item there and let
  // applyVis (user prefs) be the only thing that hides any of them.

  // landing
  if (!sub) { if (!location.hash) showHomeView(); }
  else if (!(app.primary === 'chat' && location.hash)) navigateTo(app.primary);
  // (aide with a #sessionId is already restored by initSessions)
  document.body.classList.remove('preboot', 'login-mode');
}

function _show(id, on) { const e = document.getElementById(id); if (e) e.style.display = on ? '' : 'none'; }

function renderAppCrumb(appName) {
  const crumb = document.getElementById('app-crumb');
  if (!crumb) return;
  crumb.replaceChildren();
  crumb.appendChild(document.createTextNode(appName));
  if (appName !== 'alles') {
    const parent = document.createElement('span');
    parent.textContent = ' / alles';
    crumb.appendChild(parent);
  }
  crumb.title = appName === 'alles' ? 'home' : 'back to alles';
}

// cross-app jump → full-page nav to that app's subdomain, carrying an SSO handoff code
async function crossNav(sub) {
  let url = urlForApp(sub);
  try {
    const { code } = await fetch('/api/auth/handoff').then(r => r.json());
    if (code) url += (url.includes('?') ? '&' : '?') + '_auth=' + encodeURIComponent(code);
  } catch {}
  location.assign(url);
}

function _showLoginScreen() {
  document.body.classList.remove('preboot');
  document.body.classList.add('login-mode');
  const screen = document.getElementById('login-screen');
  if (screen) screen.style.display = 'flex';
  const submit = document.getElementById('login-submit');
  if (!submit || submit.dataset.wired) return;   // re-entry must not stack listeners
  submit.dataset.wired = '1';
  submit.addEventListener('click', async () => {
    const pw = document.getElementById('login-pw')?.value;
    const r = await fetch('/api/auth/login', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    });
    if (r.ok) {
      if (screen) screen.style.display = 'none';
      document.body.classList.remove('login-mode');
      sessionStorage.removeItem('alles_sso_tried');
      if (_pendingSso) { _ssoRedirect(_pendingSso); return; }   // came from an app → relay back
      _boot();
    } else toast('wrong password', 'error');
  });
  document.getElementById('login-pw')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('login-submit')?.click();
  });
}

init();

// ── views ─────────────────────────────────────────────────────────────────────
const _VIEW_IDS = [
  'home-view', 'chat', 'notes-view', 'tasks-view', 'calendar-view', 'gallery-view',
  'models-view', 'brain-view', 'wiki-view', 'compare-view', 'vault-view', 'contacts-view',
  'reminders-view', 'files-view', 'mail-view', 'photos-view', 'subs-view', 'money-view', 'days-view', 'journal-view', 'cookbook-view', 'usage-view', 'skills-view',
];

function hideAllViews() {
  _VIEW_IDS.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
  document.getElementById('composer-outer').style.display = 'none';
}

function showView(viewId, navKey, onShow) {
  hideAllViews();
  document.getElementById(viewId).style.display = 'flex';
  setNav(navKey);
  onShow?.();
}

const showChatView = () => {
  hideAllViews();
  document.getElementById('chat').style.display = 'flex';
  document.getElementById('composer-outer').style.display = 'block';
  setNav('chat');
};
// so selectSession (sessions.js) can jump back to chat when a convo is clicked
// from a tools page — otherwise messages render behind the still-open tool view
window._enterChatView = showChatView;

// the command palette (search.js) reaches across subdomains, so expose the router
// + an "ask aide / research" handoff it can call from any app.
window._navigateTo = (v) => navigateTo(v);
window._askInChat = (q, web = false) => {
  q = (q || '').trim();
  if (!q) return;
  const ta = document.getElementById('composer-ta');
  if (ta) {   // on aide — run it inline
    showChatView();
    ta.value = q; ta.dispatchEvent(new Event('input', { bubbles: true }));
    if (web) runResearch(q); else sendMessage(q);
  } else {    // from another subapp — hop to aide carrying the query (SSO handles auth)
    location.href = urlForApp('aide') + '?ask=' + encodeURIComponent(q) + (web ? '&web=1' : '');
  }
};
const showModelsView  = () => showView('models-view',   'models',   () => renderSidebarModelList(document.getElementById('sidebar-model-search')?.value || ''));
const showBrainView   = () => showView('brain-view',    'brain',    loadBrainPanel);
const showNotesView    = () => showView('notes-view',    'notes',    loadNotes);
const showTasksView    = () => showView('tasks-view',    'tasks',    loadTasks);
const showCalendarView = () => showView('calendar-view', 'calendar', loadCalendar);
const showGalleryView  = () => showView('gallery-view',  'gallery',  () => { loadGallery(); initGalleryUpload(); });
const showCompareView  = () => showView('compare-view',  'compare',  () => { initCompareView(); loadCompareModels(); });
const showWikiView     = () => showView('wiki-view',     'wiki',     async () => { (await import('./vaultmd.js')).initVault(); });
const showVaultView      = () => showView('vault-view',      'vault',     loadVaultView);
const showContactsView   = () => showView('contacts-view',  'contacts',  () => loadContacts());
const showRemindersView  = () => showView('reminders-view', 'reminders', initReminderPanel);
const showSubsView       = () => showView('subs-view',      'subs',      async () => { (await import('./subs.js')).initSubsPanel(); });
const showMoneyView      = () => showView('money-view',     'money',     async () => { (await import('./money.js')).initMoneyPanel(); });
const showDaysView       = () => showView('days-view',      'days',      async () => { (await import('./days.js')).initDaysPanel(); });
const showJournalView    = () => showView('journal-view',   'journal',   async () => { (await import('./journal.js')).initJournal(); });
const showCookbookView   = () => showView('cookbook-view',  'cookbook',  async () => { (await import('./cookbook.js')).initCookbook(); });
const showSkillsView     = () => showView('skills-view',    'skills',    async () => { (await import('./skills.js')).initSkills(); });
const showUsageView      = () => showView('usage-view',     'usage',     async () => { (await import('./usage.js')).initUsage(); });
const showFilesView      = () => showView('files-view',     'files',     () => { initFiles(); loadFiles(); });
const showMailView       = () => showView('mail-view',      'mail',      loadMail);
const showPhotosView     = () => showView('photos-view',    'photos',    () => { initPhotos(); loadPhotos(); });
const showHomeView       = () => showView('home-view',      'home',      renderHome);

// central nav dispatch — used by both the sidebar nav-items and the home tiles
function navigateTo(v) {
  // memory now lives inside settings, not as its own view
  if (v === 'memory') { openSettings('memory'); return; }
  // a view that lives on another subdomain → full-page jump (with SSO handoff)
  if (v !== 'settings') {
    const dest = viewToSub(v);
    if (dest !== currentSub()) { crossNav(dest); return; }
  }
  if      (v === 'home')      showHomeView();
  else if (v === 'chat')      showChatView();
  else if (v === 'models')    showModelsView();
  else if (v === 'brain')     showBrainView();
  else if (v === 'notes')     showNotesView();
  else if (v === 'tasks')     showTasksView();
  else if (v === 'calendar')  showCalendarView();
  else if (v === 'gallery')   showGalleryView();
  else if (v === 'wiki')      showWikiView();
  else if (v === 'compare')   showCompareView();
  else if (v === 'vault')     showVaultView();
  else if (v === 'contacts')  showContactsView();
  else if (v === 'reminders') showRemindersView();
  else if (v === 'subs')      showSubsView();
  else if (v === 'money')     showMoneyView();
  else if (v === 'days')      showDaysView();
  else if (v === 'journal')   showJournalView();
  else if (v === 'cookbook')  showCookbookView();
  else if (v === 'usage')     showUsageView();
  else if (v === 'skills')    showSkillsView();
  else if (v === 'files')     showFilesView();
  else if (v === 'mail')      showMailView();
  else if (v === 'photos')    showPhotosView();
  else if (v === 'settings')  openSettings();
}

// ── launcher tiles ──────────────────────────────────────────────────────────
const _ICON = {
  chat: '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8z"/>',
  notes: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="13" y2="17"/>',
  calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
  tasks: '<polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
  memory: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
  secrets: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  subs: '<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
  money: '<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/>',
  days: '<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/><path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/>',
  contacts: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  reminders: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
  gallery: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
  compare: '<rect x="3" y="4" width="7" height="16" rx="1"/><rect x="14" y="4" width="7" height="16" rx="1"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><polyline points="3 7 12 13 21 7"/>',
  files: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  photos: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
  journal: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><line x1="9" y1="7" x2="15" y2="7"/>',
  cookbook: '<path d="M12 2a3 3 0 0 0-3 3c0 .6.2 1.2.5 1.7L7 9H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-2l-2.5-2.3c.3-.5.5-1.1.5-1.7a3 3 0 0 0-3-3z"/><line x1="7" y1="14" x2="17" y2="14"/>',
  skills: '<path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z"/>',
  usage: '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
};
const _svg = (k) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${_ICON[k] || ''}</svg>`;

const HOME_TILES = [
  { view: 'chat',     name: 'aide',     desc: 'chat, agent',     icon: 'chat' },
  { view: 'mail',     name: 'mail',     desc: 'inbox & sending', icon: 'mail' },
  { view: 'wiki',     name: 'docs',     desc: 'linked notes',    icon: 'notes' },
  { view: 'files',    name: 'files',    desc: 'your files',      icon: 'files' },
  { view: 'calendar', name: 'calendar', desc: 'schedule',        icon: 'calendar' },
  { view: 'tasks',    name: 'tasks',    desc: 'to-dos',          icon: 'tasks' },
  { view: 'photos',   name: 'gallery',  desc: 'photos',          icon: 'photos' },
  { view: 'contacts', name: 'contacts', desc: 'people',          icon: 'contacts' },
  { view: 'vault',    name: 'secrets',  desc: 'passwords',       icon: 'secrets' },
  { view: 'subs',     name: 'subs',     desc: 'recurring costs', icon: 'subs' },
  { view: 'money',    name: 'money',    desc: 'accounts & budgets', icon: 'money' },
  { view: 'days',     name: 'days',     desc: 'countdowns',      icon: 'days' },
  { view: 'journal',  name: 'journal',  desc: 'daily entries',   icon: 'journal' },
];

// ── home tiles: drag-reorder + hide/show (persisted) + quick capture ─────────
const HOME_ORDER_KEY = 'alles-home-order';
const HOME_HIDDEN_KEY = 'alles-home-hidden';
let _homeEdit = false, _homeAnimated = false, _dragView = null;

const _homeOrder = () => { try { return JSON.parse(localStorage.getItem(HOME_ORDER_KEY) || '[]'); } catch { return []; } };
const _homeHidden = () => { try { return JSON.parse(localStorage.getItem(HOME_HIDDEN_KEY) || '[]'); } catch { return []; } };
function _orderedTiles() {
  const pos = new Map(_homeOrder().map((v, i) => [v, i]));
  return [...HOME_TILES].sort((a, b) => (pos.get(a.view) ?? 999) - (pos.get(b.view) ?? 999));
}

function renderHome() {
  const grid = document.getElementById('home-grid');
  if (!grid) return;
  _renderHomeTiles();
  _renderHomeGreeting();
  _renderFirstRun();
  _renderToday();
  _startHomeClock();
  _wireQuickCapture();
  _wireHomeAsk();
}

// "ask aide about my day" — a simple, tool-free aide right on the home page, with
// its own model switcher. pure chat (no research/agent), but day-aware: it tucks a
// quick summary of today in front of your question so it can actually answer.
let _haSession = null, _haAttach = '';
async function _wireHomeAsk() {
  const inp = document.getElementById('ha-input');
  const sel = document.getElementById('ha-model');
  const send = document.getElementById('ha-send');
  const rep = document.getElementById('home-ask-reply');
  if (!inp || inp.dataset.wired) return;
  inp.dataset.wired = '1';
  try {
    const eps = await fetch('/api/models').then(r => r.json());
    sel.innerHTML = '';
    for (const e of eps) for (const m of (e.cached_models || e.models || []))
      sel.insertAdjacentHTML('beforeend', `<option value="${e.id}::${m}">${e.name} / ${m}</option>`);
    if (!sel.options.length) sel.insertAdjacentHTML('beforeend', '<option value="">no model — add one in settings</option>');
  } catch {}

  document.getElementById('ha-upload')?.addEventListener('click', () => document.getElementById('ha-file')?.click());
  document.getElementById('ha-file')?.addEventListener('change', async e => {
    const f = e.target.files[0]; if (!f) return;
    try { _haAttach = `\n\n[attached ${f.name}]:\n` + (await f.text()).slice(0, 4000); toast(`attached ${f.name}`, 'success'); }
    catch { toast('could not read that file', 'error'); }
  });
  document.getElementById('ha-goto')?.addEventListener('click', () => navigateTo('chat'));
  document.getElementById('ha-voice')?.addEventListener('click', async () => {
    try { (await import('./voice.js')).dictateInto?.(inp); }
    catch { toast('voice input lives in the full aide', 'error'); }
  });

  const ask = async () => {
    const q = inp.value.trim(); if (!q) return;
    const [eid, model] = (sel.value || '::').split('::');
    if (!eid) { toast('add a model in settings first', 'error'); return; }
    rep.style.display = 'block'; rep.textContent = '…'; send.disabled = true;
    // day context so the simple aide can actually talk about today
    let ctx = '';
    try {
      const d = await fetch('/api/today').then(r => r.json());
      const bits = [];
      if (d.events?.length) bits.push('events: ' + d.events.map(e => `${e.time || 'all-day'} ${e.title}`).join('; '));
      if (d.tasks?.overdue?.length) bits.push('overdue: ' + d.tasks.overdue.map(t => t.title).join('; '));
      if (d.tasks?.due_today?.length) bits.push('due today: ' + d.tasks.due_today.map(t => t.title).join('; '));
      if (d.reminders?.length) bits.push('reminders: ' + d.reminders.map(r => r.text).join('; '));
      if (bits.length) ctx = `(my day so far — ${bits.join(' | ')})\n\n`;
    } catch {}
    if (!_haSession) {
      _haSession = (await fetch('/api/sessions', { method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name: 'home: ask aide', model, endpoint_id: eid, incognito: true }) }).then(x => x.json())).id;
    }
    let text = '';
    try {
      const resp = await fetch('/api/chat', { method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ session_id: _haSession, message: ctx + q + _haAttach, mode: 'chat', simple: true }) });
      const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = '';
      for (;;) {
        const { done, value } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, i); buf = buf.slice(i + 2);
          if (line.startsWith('data: ')) {
            const dd = line.slice(6); if (dd === '[DONE]') break;
            try { const ev = JSON.parse(dd); if (ev.delta) { text += ev.delta; rep.innerHTML = mdToHtml(text); } } catch {}
          }
        }
      }
    } catch { rep.textContent = 'failed — try again'; }
    send.disabled = false; inp.value = ''; _haAttach = '';
  };
  send.addEventListener('click', ask);
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); ask(); } });
}

// fresh-install nudge: if no AI provider is wired up yet, chat is a dead end —
// show a get-started card on the launcher instead of letting them find out the hard way
async function _renderFirstRun() {
  const el = document.getElementById('home-firstrun');
  if (!el) return;
  if (localStorage.getItem('alles-firstrun-dismissed') === '1') { el.style.display = 'none'; return; }
  let st;
  try { st = await fetch('/api/setup/status').then(r => r.json()); }
  catch { el.style.display = 'none'; return; }   // never let this block the launcher
  if (st.configured) { el.style.display = 'none'; el.innerHTML = ''; return; }   // already connected → gone
  el.style.display = 'block';
  el.innerHTML = `
    <button class="firstrun-x" id="firstrun-x" title="dismiss" aria-label="dismiss">×</button>
    <div class="firstrun-title">👋 welcome to alles</div>
    <div class="firstrun-body">to start chatting, connect an AI provider — paste an API key (DeepSeek, Anthropic, OpenAI…) or point at a local Ollama. takes about a minute.</div>
    <button class="btn firstrun-cta" id="firstrun-setup-btn">set up a provider</button>`;
  document.getElementById('firstrun-setup-btn')?.addEventListener('click', () => openSettings('models'));
  document.getElementById('firstrun-x')?.addEventListener('click', () => {
    localStorage.setItem('alles-firstrun-dismissed', '1');
    el.style.display = 'none';
  });
}

function _renderHomeTiles() {
  const grid = document.getElementById('home-grid');
  if (!grid) return;
  const hidden = new Set(_homeHidden());
  const tiles = _orderedTiles();
  const shown = _homeEdit ? tiles : tiles.filter(t => !hidden.has(t.view));
  grid.classList.toggle('editing', _homeEdit);
  grid.classList.toggle('no-anim', _homeAnimated);
  grid.innerHTML = shown.map((t, i) => {
    const isHidden = hidden.has(t.view);
    return `<div class="home-tile${isHidden ? ' hidden-tile' : ''}" data-go="${t.view}" draggable="${_homeEdit}" style="--i:${i}">
      <span class="home-tile-icon">${_svg(t.icon || t.view)}</span>
      <span class="home-tile-name">${t.name}</span>
      <span class="home-tile-desc">${t.desc}</span>
      ${_homeEdit ? `<button class="home-tile-toggle" data-toggle="${t.view}" title="${isHidden ? 'show' : 'hide'}">${isHidden ? '+' : '×'}</button>` : ''}
    </div>`;
  }).join('');
  _homeAnimated = true;
  grid.querySelectorAll('.home-tile').forEach(el => {
    el.addEventListener('click', e => {
      if (_homeEdit || e.target.closest('.home-tile-toggle')) return;
      navigateTo(el.dataset.go);
    });
    if (_homeEdit) _bindTileDrag(el);
  });
  grid.querySelectorAll('.home-tile-toggle').forEach(b =>
    b.addEventListener('click', e => { e.stopPropagation(); _toggleTileHidden(b.dataset.toggle); }));
}

function _toggleHomeEdit() {
  _homeEdit = !_homeEdit;
  const btn = document.getElementById('home-edit-btn');
  if (btn) { btn.classList.toggle('active', _homeEdit); btn.textContent = _homeEdit ? 'done' : 'customize'; }
  _renderHomeTiles();
}
function _toggleTileHidden(view) {
  const h = new Set(_homeHidden());
  h.has(view) ? h.delete(view) : h.add(view);
  localStorage.setItem(HOME_HIDDEN_KEY, JSON.stringify([...h]));
  _renderHomeTiles();
}
function _clearDropMarks() {
  document.querySelectorAll('.home-tile.drop-before, .home-tile.drop-after')
    .forEach(t => t.classList.remove('drop-before', 'drop-after'));
}
function _bindTileDrag(el) {
  el.addEventListener('dragstart', e => { _dragView = el.dataset.go; e.dataTransfer.effectAllowed = 'move'; el.classList.add('dragging'); });
  el.addEventListener('dragend', () => { el.classList.remove('dragging'); _dragView = null; _clearDropMarks(); });
  el.addEventListener('dragover', e => {
    if (!_dragView || el.dataset.go === _dragView) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'move';
    const r = el.getBoundingClientRect();
    const after = e.clientX > r.left + r.width / 2;   // which side of the tile → where the bar shows
    _clearDropMarks();
    el.classList.add(after ? 'drop-after' : 'drop-before');
  });
  el.addEventListener('dragleave', () => el.classList.remove('drop-before', 'drop-after'));
  el.addEventListener('drop', e => {
    e.preventDefault();
    const from = _dragView, to = el.dataset.go;
    const after = el.classList.contains('drop-after');
    _clearDropMarks();
    if (!from || !to || from === to) return;
    const order = _orderedTiles().map(t => t.view).filter(v => v !== from);
    let idx = order.indexOf(to);
    if (after) idx += 1;
    order.splice(idx, 0, from);
    localStorage.setItem(HOME_ORDER_KEY, JSON.stringify(order));
    _renderHomeTiles();
  });
}

// quick capture → today's daily note (bullet) or a task
let _qcWired = false, _qcMode = 'note';
function _wireQuickCapture() {
  if (_qcWired) return; _qcWired = true;
  const inp = document.getElementById('hc-input'), save = document.getElementById('hc-save');
  document.getElementById('home-edit-btn')?.addEventListener('click', _toggleHomeEdit);
  document.getElementById('home-settings-btn')?.addEventListener('click', () => openSettings('appearance', true));
  document.querySelectorAll('.hc-mode').forEach(b => b.addEventListener('click', () => {
    _qcMode = b.dataset.mode;
    document.querySelectorAll('.hc-mode').forEach(x => x.classList.toggle('active', x === b));
    if (inp) inp.placeholder = _qcMode === 'task' ? 'capture a task…' : 'capture a note…';
  }));
  const submit = async () => {
    const text = (inp?.value || '').trim();
    if (!text) return;
    save.disabled = true;
    const ok = await _quickCapture(text, _qcMode === 'task');
    save.disabled = false;
    if (ok) { inp.value = ''; toast(_qcMode === 'task' ? 'task added' : 'note saved', 'success'); _renderToday(); }
    else toast('capture failed', 'error');
  };
  save?.addEventListener('click', submit);
  inp?.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } });
}
// derive a doc title from the note's text — its first line, cleaned up. so a quick
// note names itself after what you wrote instead of getting a date stamp.
function _titleFromText(text) {
  let t = (text || '').trim().split('\n')[0].replace(/^#+\s*/, '').replace(/^[-*]\s+(\[[ xX]\]\s+)?/, '').trim();
  t = t.replace(/[\\/:*?"<>|#\[\]]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (t.length > 60) t = t.slice(0, 60).replace(/\s+\S*$/, '').trim();   // don't cut mid-word
  return t || 'note';
}
async function _quickCapture(text, asTask) {
  try {
    if (asTask) {
      await api('/api/tasks', { method: 'POST', body: { title: text } });
      return true;
    }
    // a standalone note named from its content, with a free (non-clobbering) name
    const title = _titleFromText(text);
    let taken = new Set();
    try { taken = new Set(((await api('/api/vault-md/names')).names || []).map(n => n.toLowerCase())); } catch {}
    let name = title, i = 2;
    while (taken.has(name.toLowerCase())) name = `${title} ${i++}`;
    await api('/api/vault-md/file', { method: 'POST', body: { path: name, content: text.trim() + '\n' } });
    return true;
  } catch { return false; }
}

// ── today strip: events, tasks, reminders, renewals, mail, recent docs ──────
const _escT = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

async function _renderToday() {
  const el = document.getElementById('home-today');
  if (!el) return;
  const local = new Date();
  const dstr = `${local.getFullYear()}-${String(local.getMonth() + 1).padStart(2, '0')}-${String(local.getDate()).padStart(2, '0')}`;
  let d;
  try { d = await fetch(`/api/today?date=${dstr}`).then(r => r.json()); }
  catch { el.style.display = 'none'; return; }

  // unread mail straight from the inbox cache — instant, no IMAP round-trip
  let unread = [];
  try {
    for (const k of Object.keys(localStorage)) {
      if (!k.startsWith('mail-cache-') || k.endsWith('-sent')) continue;
      for (const m of JSON.parse(localStorage.getItem(k) || '[]')) {
        if (!m.seen && !unread.find(x => x.uid === m.uid && x.account_id === m.account_id)) unread.push(m);
      }
    }
  } catch {}

  const rows = [];
  const row = (go, icon, html) => rows.push(`<div class="ht-row" data-go="${go}"><span class="ht-ico">${icon}</span><span class="ht-body">${html}</span></div>`);

  for (const e of d.events.slice(0, 4))
    row('calendar', '◷', `${e.time ? `<b>${e.time}</b> ` : ''}${_escT(e.title)}`);
  for (const t of d.tasks.overdue.slice(0, 3))
    row('tasks', '!', `<span class="ht-warn">overdue</span> ${_escT(t.title)}`);
  for (const t of d.tasks.due_today.slice(0, 3))
    row('tasks', '☐', `due today — ${_escT(t.title)}`);
  for (const r of d.reminders.slice(0, 3))
    row('reminders', '◔', `<b>${r.at}</b> ${_escT(r.text)}`);
  for (const s of d.renewing.slice(0, 3))
    row('subs', '↻', `${_escT(s.name)} renews ${s.in_days === 0 ? 'today' : s.in_days === 1 ? 'tomorrow' : `in ${s.in_days}d`}${s.price ? ` — ${_escT(s.currency)}${s.price}` : ''}`);
  for (const e of d.day_events.slice(0, 2))
    row('days', '⧗', `${_escT(e.name)} ${e.in_days === 0 ? 'is today' : `in ${e.in_days}d`}`);
  if (unread.length)
    row('mail', '✉', `${unread.length} unread — ${_escT((unread[0].subject || '').slice(0, 50))}`);

  // recents aren't "today" items — when they're all we have, lead with the
  // clear-day note so the strip still reads as a day view
  const scheduled = rows.length;
  for (const doc of (d.recent_docs || []).slice(0, 2))
    row('wiki', '≡', `recent: ${_escT(doc.name)}`);

  const empty = scheduled ? '' : '<div class="ht-empty">nothing scheduled — clear day ✨</div>';
  el.innerHTML = `${empty}${rows.length ? `<div class="ht-rows">${rows.join('')}</div>` : ''}
    <button class="btn" id="ht-ask">ask aide about my day</button>`;
  el.style.display = 'flex';

  el.querySelectorAll('.ht-row').forEach(r => r.addEventListener('click', () => navigateTo(r.dataset.go)));
  document.getElementById('ht-ask')?.addEventListener('click', () => _askAideAboutToday(d, unread));
}

function _askAideAboutToday(d, unread) {
  const bits = [];
  if (d.events.length) bits.push(`events: ${d.events.map(e => `${e.time || 'all-day'} ${e.title}`).join('; ')}`);
  if (d.tasks.overdue.length) bits.push(`overdue tasks: ${d.tasks.overdue.map(t => t.title).join('; ')}`);
  if (d.tasks.due_today.length) bits.push(`tasks due today: ${d.tasks.due_today.map(t => t.title).join('; ')}`);
  if (d.reminders.length) bits.push(`reminders: ${d.reminders.map(r => `${r.at} ${r.text}`).join('; ')}`);
  if (d.renewing.length) bits.push(`renewing soon: ${d.renewing.map(s => `${s.name} in ${s.in_days}d`).join('; ')}`);
  if (unread.length) bits.push(`unread mail: ${unread.slice(0, 5).map(m => m.subject).join('; ')}`);
  const ctx = bits.length ? `here's my day:\n${bits.join('\n')}` : 'my schedule is empty today.';
  showChatView();
  newChat();
  sendMessage(`${ctx}\n\ngive me a short, friendly rundown of my day — what to do first, what can wait, anything i'm about to miss.`);
}

// a different one every visit — picked by time of day
const _GREETINGS = {
  night: ['still up?', 'the quiet hours', 'burning the midnight oil', 'night owl mode',
          '3am thoughts?', "the world's asleep", 'moonlight session', 'late night, big ideas',
          'insomnia or inspiration?', 'the night shift'],
  morning: ['good morning', 'rise and shine', 'coffee first', 'a fresh one', 'up and at it',
            'new day, clean slate', 'morning, sunshine', "let's get this day", 'early bird hours',
            'the day is yours', 'ready when you are', 'top of the morning'],
  afternoon: ['good afternoon', 'midday check-in', 'keeping the momentum', 'halfway there',
              'afternoon focus', 'the day is in full swing', 'cruising along', 'post-lunch power',
              'steady as she goes', 'making it count', 'deep in the day'],
  evening: ['good evening', 'winding down?', 'home stretch', 'golden hour', 'evening calm',
            'the night is young', 'lights low, focus up', "day's almost done", 'evening session',
            'one more thing?', 'the day did its part'],
};

function _renderHomeGreeting() {
  const el = document.getElementById('home-greeting');
  if (!el) return;
  const h = new Date().getHours();
  const pool = h < 5 ? _GREETINGS.night : h < 12 ? _GREETINGS.morning
             : h < 18 ? _GREETINGS.afternoon : _GREETINGS.evening;
  const phrase = pool[Math.floor(Math.random() * pool.length)];
  const name = (localStorage.getItem('alles-name') || '').trim();
  el.replaceChildren();
  if (name) {
    // "still up, eric?" — the name slips in before any ?/! punctuation
    const punct = /[?!]$/.test(phrase) ? phrase.slice(-1) : '';
    el.appendChild(document.createTextNode((punct ? phrase.slice(0, -1) : phrase) + ', '));
    const s = document.createElement('span');
    s.className = 'accent';
    s.textContent = name;
    el.appendChild(s);
    if (punct) el.appendChild(document.createTextNode(punct));
  } else {
    el.appendChild(document.createTextNode(phrase));
  }
  // greeting doubles as the way in to set your name
  el.title = 'click to set your name';
  el.style.cursor = 'pointer';
  if (!el.dataset.wired) {
    el.dataset.wired = '1';
    el.addEventListener('click', () => openSettings('appearance'));
  }
  let tag = document.getElementById('home-tagline');
  if (!tag) {
    tag = document.createElement('div');
    tag.id = 'home-tagline';
    tag.className = 'home-tagline';
    el.insertAdjacentElement('afterend', tag);
  }
  tag.textContent = 'your everything, in one place';
}

let _homeClockTimer = null;
function _startHomeClock() {
  const tick = () => {
    const el = document.getElementById('home-clock');
    if (!el) return;
    const now = new Date();
    const date = now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' }).toLowerCase();
    const time = now.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).toLowerCase();
    el.textContent = `${date} · ${time}`;
  };
  tick();
  if (!_homeClockTimer) _homeClockTimer = setInterval(tick, 20000);
}

// aide's tools live in the collapsible "tools" group
const _moreViews = new Set(['compare','gallery','brain','models','reminders','subs','days']);

function setNav(view) {
  document.querySelectorAll('.nav-item').forEach(n => {
    n.classList.toggle('active', n.dataset.view === view);
  });
  // auto-expand tools section if navigating to a hidden item
  if (_moreViews.has(view)) {
    const items = document.getElementById('nav-more-items');
    const arrow = document.getElementById('nav-more-arrow');
    if (items && !items.classList.contains('open')) {
      items.classList.add('open');
      if (arrow) arrow.textContent = '▴';
      localStorage.setItem('nav-more-open', '1');
    }
  }
}

// ── events ────────────────────────────────────────────────────────────────────
let _eventsBound = false;

function bindEvents() {
  if (_eventsBound) return;
  _eventsBound = true;

  // tools collapse toggle
  const moreToggle = document.getElementById('nav-more-toggle');
  const moreItems  = document.getElementById('nav-more-items');
  const moreArrow  = document.getElementById('nav-more-arrow');
  if (moreToggle && moreItems) {
    if (localStorage.getItem('nav-more-open') !== '0') {   // open by default
      moreItems.classList.add('open');
      if (moreArrow) moreArrow.textContent = '▴';
    }
    moreToggle.addEventListener('click', () => {
      const isOpen = moreItems.classList.toggle('open');
      if (moreArrow) moreArrow.textContent = isOpen ? '▴' : '▾';
      localStorage.setItem('nav-more-open', isOpen ? '1' : '0');
    });
  }

  const ta = document.getElementById('composer-ta');

  ta.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); }
  });
  // dim send when empty (but never while recording — it doubles as the stop)
  const _sendBtn = document.getElementById('send-btn');
  const syncSend = () => { _sendBtn.classList.toggle('is-empty', !ta.value.trim() && !_sendBtn.classList.contains('recording')); };
  ta.addEventListener('input', syncSend);
  syncSend();
  _sendBtn.addEventListener('click', async () => {
    const { isRecording, stopRecording } = await import('./voice.js');
    if (isRecording()) stopRecording();
    else doSend();
  });
  // right-click send → schedule the message for later (delivered by the
  // reminder loop as a type=message reminder bound to this session)
  _sendBtn.addEventListener('contextmenu', e => {
    e.preventDefault();
    const text = ta.value.trim();
    if (!text) { toast('type a message first — then right-click to schedule it', ''); return; }
    _openSchedulePop(text, ta);
  });
  document.getElementById('stop-btn').addEventListener('click', stopStream);
  document.getElementById('conn-banner-x')?.addEventListener('click', hideConnBanner);

  document.getElementById('new-chat-btn').addEventListener('click', () => {
    showChatView();
    newChat();   // fresh chat — not persisted until first message
  });

  document.getElementById('session-search').addEventListener('input', e => renderSidebar(e.target.value));
  document.getElementById('sidebar-model-search')?.addEventListener('input', e => renderSidebarModelList(e.target.value));
  document.getElementById('models-refresh-btn')?.addEventListener('click', loadModels);
  document.getElementById('brain-refresh-btn')?.addEventListener('click', loadBrainPanel);
  document.getElementById('brain-open-memory-btn')?.addEventListener('click', () => openSettings('memory'));

  const toggleResearch = () => {
    const on = !isResearchMode();
    setResearchMode(on);
    if (on) setDocsMode(false);   // research + docs are mutually exclusive
    document.getElementById('research-toggle-btn').classList.toggle('active', on);
    ta.placeholder = on ? 'research a topic...' : 'message aide...';
  };

  const toggleDocs = () => {
    const on = !isDocsMode();
    setDocsMode(on);
    if (on) setResearchMode(false);
    ta.placeholder = on ? 'ask your docs...' : 'message aide...';
  };

  document.querySelector('.c-tools')?.addEventListener('click', e => {
    const btn = e.target.closest('button');
    if (!btn) return;
    if (btn.id === 'research-toggle-btn') {
      e.preventDefault();
      e.stopPropagation();
      toggleResearch();
    } else if (btn.id === 'docs-toggle-btn') {
      e.preventDefault();
      e.stopPropagation();
      toggleDocs();
    } else if (btn.id === 'incognito-btn') {
      e.preventDefault();
      e.stopPropagation();
      toggleIncognitoMode();
    } else if (btn.id === 'more-tools-btn') {
      e.preventDefault();
      e.stopPropagation();
      toggleMoreTools();
    }
  });

  document.getElementById('shell-btn-tool').addEventListener('click', openShellPanel);
  document.getElementById('shell-panel-close')?.addEventListener('click', closeShellPanel);
  document.getElementById('shell-send-btn')?.addEventListener('click', submitShellPanel);
  document.getElementById('shell-input')?.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeShellPanel();
    } else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      submitShellPanel();
    }
  });
  document.getElementById('mode-agent').addEventListener('click', () => setMode('agent'));
  document.getElementById('mode-chat').addEventListener('click',  () => setMode('chat'));
  // permission mode button + label
  const permBtn = document.getElementById('perm-mode-btn');
  if (permBtn) {
    setPermMode(getPermMode());   // sets label span + classes (keeps the icon)
    permBtn.addEventListener('click', e => { e.stopPropagation(); _openPermMenu(permBtn); });
  }
  const effortBtn = document.getElementById('effort-btn');
  if (effortBtn) {
    setEffort(getEffort());
    effortBtn.addEventListener('click', e => { e.stopPropagation(); _openEffortMenu(effortBtn); });
  }
  document.getElementById('theme-btn')?.addEventListener('click', toggleTheme);   // removed from topbar → lives in settings → appearance
  document.getElementById('topbar-settings-btn')?.addEventListener('click', openSettings);

  // your name → used by aide's greeting (client-only, no server round-trip)
  const nameInput = document.getElementById('s-user-name');
  if (nameInput) {
    nameInput.value = localStorage.getItem('alles-name') || '';
    nameInput.addEventListener('input', () => localStorage.setItem('alles-name', nameInput.value.trim()));
  }
  document.getElementById('app-crumb')?.addEventListener('click', () => {
    if (currentSub()) crossNav('');
    else showHomeView();
  });

  // persona picker
  document.getElementById('persona-btn').addEventListener('click', openPersonaPicker);

  // model picker
  document.getElementById('model-btn').addEventListener('click', openModelModal);
  document.getElementById('model-modal-close').addEventListener('click', closeAllModals);
  document.getElementById('model-search-input').addEventListener('input', e => renderModelList(e.target.value));

  // export/share/print dropdown
  document.getElementById('session-actions-btn')?.addEventListener('click', e => {
    e.stopPropagation();
    const existing = document.getElementById('_export_menu');
    if (existing) { existing.remove(); return; }
    const btn = e.currentTarget;
    const rect = btn.getBoundingClientRect();
    const menu = document.createElement('div');
    menu.id = '_export_menu';
    menu.className = 'ctx-menu';
    menu.style.cssText = `display:block;right:${window.innerWidth - rect.right}px;top:${rect.bottom + 4}px;left:auto`;
    menu.innerHTML = `
      <div class="ctx-item" data-a="export">export markdown</div>
      <div class="ctx-item" data-a="share">copy share link</div>
      <div class="ctx-item" data-a="print">print / save pdf</div>`;
    menu.addEventListener('click', e => {
      const a = e.target.closest('.ctx-item')?.dataset.a;
      if (a === 'export') exportActiveSessionMarkdown();
      if (a === 'share')  _shareSession();
      if (a === 'print')  _printSession();
      menu.remove();
    });
    document.body.appendChild(menu);
    setTimeout(() => document.addEventListener('click', () => menu.remove(), { once: true }), 0);
  });
  document.getElementById('sidebar-toggle-btn')?.addEventListener('click', () => {
    if (!document.body.classList.contains('is-aide')) return;
    document.body.classList.toggle('sidebar-hidden');
    localStorage.setItem('aide-sidebar-hidden', document.body.classList.contains('sidebar-hidden') ? '1' : '');
  });

  // notes / tasks / calendar / gallery
  document.getElementById('note-new-btn').addEventListener('click', newNote);
  document.getElementById('cal-new-btn').addEventListener('click', newEvent);
  const calQuick = document.getElementById('cal-quick');
  calQuick?.addEventListener('keydown', async e => {
    if (e.key !== 'Enter' || !calQuick.value.trim()) return;
    await fetch('/api/calendar/quick', { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: calQuick.value.trim() }) });
    calQuick.value = '';
    loadCalendar();
  });
  const taskInput = document.getElementById('task-add-input');
  document.getElementById('task-add-btn').addEventListener('click', async () => {
    await addTask(taskInput.value.trim()); taskInput.value = '';
  });
  taskInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('task-add-btn').click();
  });

  // attach button
  document.getElementById('attach-btn')?.addEventListener('click', () => {
    document.getElementById('file-input-hidden')?.click();
  });
  document.getElementById('file-input-hidden')?.addEventListener('change', async e => {
    for (const f of e.target.files) await attachFile(f);
    e.target.value = '';
  });

  // mic
  document.getElementById('mic-btn')?.addEventListener('click', async () => {
    const { isRecording, startRecording, stopRecording } = await import('./voice.js');
    if (isRecording()) stopRecording(); else startRecording();
  });

  // incognito
  setIncognitoMode(false);


  // contacts
  document.getElementById('contacts-search')?.addEventListener('input', e => loadContacts(e.target.value));
  document.getElementById('contact-add-btn')?.addEventListener('click', addContact);
  document.getElementById('contacts-import-btn')?.addEventListener('click', () => document.getElementById('contacts-import-input')?.click());
  document.getElementById('contacts-import-input')?.addEventListener('change', async e => {
    const f = e.target.files[0]; e.target.value = '';
    if (!f) return;
    const vcard = await f.text();
    const r = await fetch('/api/contacts/import', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ vcard }) });
    const d = await r.json().catch(() => ({}));
    toast(`imported ${d.imported || 0} contact${d.imported === 1 ? '' : 's'}`, 'success');
    loadContacts();
  });

  // sidebar nav + brand-as-home
  document.querySelectorAll('.nav-item').forEach(el => {
    el.addEventListener('click', () => navigateTo(el.dataset.view));
  });
  document.getElementById('brand-home')?.addEventListener('click', () => {
    if (currentSub()) crossNav('');   // on an app subdomain → back to the hub (with SSO handoff)
    else showHomeView();
  });

  // modal overlays close on backdrop click (except settings which manages itself)
  document.querySelectorAll('.modal-overlay:not(#settings-modal)').forEach(o => {
    o.addEventListener('click', e => { if (e.target === o) closeAllModals(); });
  });

  document.addEventListener('keydown', e => {
    const shortcuts = loadShortcuts();
    if (e.key === 'Escape') { closeAllModals(); closeSettings(); closeSearch(); closeMoreTools(); closeShellPanel(); }
    else if (matchesShortcut(e, shortcuts.search)) { e.preventDefault(); openSearch(); }
    else if (matchesShortcut(e, shortcuts.settings)) { e.preventDefault(); openSettings(); }
    else if (matchesShortcut(e, shortcuts.sidebar) && document.body.classList.contains('is-aide')) { e.preventDefault(); document.body.classList.toggle('sidebar-hidden'); }
    else if (matchesShortcut(e, shortcuts.new_chat)) { e.preventDefault(); document.getElementById('new-chat-btn')?.click(); }
    else if (matchesShortcut(e, shortcuts.send)) { e.preventDefault(); doSend(); }
  });
  document.addEventListener('click', () => {
    document.getElementById('ctx-menu').style.display = 'none';
    closeMoreTools();
  });
  // share-btn removed — export/share/print now in topbar-session-actions

  setInterval(loadModels, 30000);
}

async function _shareSession() {
  const sid = window._currentSession?.id;
  if (!sid) { toast('open a chat first', 'error'); return; }
  const btn = document.getElementById('session-share-btn');
  btn.textContent = '...'; btn.disabled = true;
  try {
    const r = await fetch(`/api/sessions/${sid}/share`, { method: 'POST' });
    const { url } = await r.json();
    const full = location.origin + url;
    await navigator.clipboard.writeText(full);
    toast('share link copied to clipboard', 'success');
  } catch { toast('share failed', 'error'); }
  btn.textContent = 'share'; btn.disabled = false;
}

function _printSession() {
  const sid = window._currentSession?.id;
  if (!sid) { window.print(); return; }
  // check if a share link exists, else just print current page
  fetch(`/api/sessions/${sid}/share`, { method: 'POST' })
    .then(r => r.json())
    .then(({ url }) => {
      const w = window.open(location.origin + url, '_blank');
      setTimeout(() => w?.print(), 600);
    })
    .catch(() => window.print());
}

function toggleMoreTools() {
  const existing = document.getElementById('_more_tools_menu');
  if (existing) { closeMoreTools(); return; }
  const btn = document.getElementById('more-tools-btn');
  const rect = btn.getBoundingClientRect();
  const menu = document.createElement('div');
  menu.id = '_more_tools_menu';
  menu.className = 'ctx-menu more-tools-menu';
  menu.style.display = 'block';
  menu.style.left = Math.max(12, rect.right - 170) + 'px';
  menu.style.top = Math.max(12, rect.top - 136) + 'px';
  menu.innerHTML = `
    <div class="ctx-item" data-tool="incognito">incognito mode</div>
    <div class="ctx-item" data-tool="research">research mode</div>
    <div class="ctx-item" data-tool="shell">shell command</div>
    <div class="ctx-item" data-tool="attach">attach file</div>
  `;
  menu.addEventListener('click', e => {
    e.stopPropagation();
    const tool = e.target.closest('.ctx-item')?.dataset.tool;
    if (tool === 'incognito') document.getElementById('incognito-btn')?.click();
    if (tool === 'research') document.getElementById('research-toggle-btn')?.click();
    if (tool === 'shell') document.getElementById('shell-btn-tool')?.click();
    if (tool === 'attach') document.getElementById('attach-btn')?.click();
    closeMoreTools();
  });
  document.body.appendChild(menu);
  btn.setAttribute('aria-expanded', 'true');
}

function closeMoreTools() {
  document.getElementById('_more_tools_menu')?.remove();
  document.getElementById('more-tools-btn')?.setAttribute('aria-expanded', 'false');
}

// ── send ──────────────────────────────────────────────────────────────────────
async function doSend() {
  const ta = document.getElementById('composer-ta');
  const text = ta.value.trim();
  if (!text) return;
  if (await tryExecuteSlashCommand(text)) {
    ta.value = ''; ta.style.height = 'auto';
    return;
  }
  ta.value = ''; ta.style.height = 'auto';
  if (isResearchMode()) runResearch(text);
  else if (isDocsMode()) runDocsQuery(text);
  else sendMessage(text);
}

// schedule-send popup (right-click on the send button)
async function _openSchedulePop(text, ta) {
  document.querySelector('.schedule-pop')?.remove();
  const pop = document.createElement('div');
  pop.className = 'schedule-pop';
  pop.innerHTML = `
    <div class="schedule-pop-title">send later</div>
    <div class="date-input" id="schedule-when" data-type="datetime" data-ph="when to send"></div>
    <div class="schedule-pop-actions">
      <button class="btn primary" id="schedule-go">schedule</button>
      <button class="btn" id="schedule-cancel">cancel</button>
    </div>`;
  document.body.appendChild(pop);
  const btnRect = document.getElementById('send-btn').getBoundingClientRect();
  pop.style.right = `${Math.max(8, window.innerWidth - btnRect.right)}px`;
  pop.style.bottom = `${Math.max(8, window.innerHeight - btnRect.top + 8)}px`;
  const { initDatePicker } = await import('./datepick.js');
  const when = pop.querySelector('#schedule-when');
  initDatePicker(when);
  const close = () => { pop.remove(); document.removeEventListener('click', outside); };
  const outside = e => { if (!pop.contains(e.target) && !document.querySelector('.date-panel')?.contains(e.target)) close(); };
  setTimeout(() => document.addEventListener('click', outside), 0);
  pop.querySelector('#schedule-cancel').addEventListener('click', close);
  pop.querySelector('#schedule-go').addEventListener('click', async () => {
    const at = when.value;
    if (!at) { toast('pick a time', 'error'); return; }
    if (new Date(at) <= new Date()) { toast('that time is in the past', 'error'); return; }
    let sid = getActiveId();
    if (!sid) {
      const s = await createSession();
      sid = s?.id;
    }
    if (!sid) { toast('no session to schedule into', 'error'); return; }
    const r = await fetch('/api/reminders', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text, trigger_at: at, type: 'message', session_id: sid }),
    });
    if (!r.ok) { toast('failed to schedule', 'error'); return; }
    ta.value = ''; ta.style.height = 'auto'; ta.dispatchEvent(new Event('input'));
    toast(`scheduled — aide will answer it ${new Date(at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).toLowerCase()}`, 'success');
    close();
  });
}

// ── mode / theme ──────────────────────────────────────────────────────────────
function setMode(m) {
  document.getElementById('mode-agent').classList.toggle('active', m === 'agent');
  document.getElementById('mode-chat').classList.toggle('active', m === 'chat');
  // .agent-mode grows the box + reveals the agent control row (CSS-driven)
  document.querySelector('.composer-box')?.classList.toggle('agent-mode', m === 'agent');
}

function _openPermMenu(anchor) {
  document.getElementById('perm-menu')?.remove();
  const cur = getPermMode();
  const opts = [
    ['approve',  'approve',  'ask before each change (recommended)'],
    ['full_auto','auto',     '⚠ runs everything without asking'],
    ['plan',     'plan',     'read-only — just make a plan, change nothing'],
  ];
  const menu = document.createElement('div');
  menu.id = 'perm-menu';
  menu.className = 'perm-menu';
  menu.innerHTML = opts.map(([v, label, desc]) =>
    `<div class="perm-menu-item${v === cur ? ' active' : ''}${v === 'full_auto' ? ' warn' : ''}" data-v="${v}">
       <div class="perm-menu-label">${label}</div>
       <div class="perm-menu-desc">${desc}</div>
     </div>`).join('');
  document.body.appendChild(menu);
  const r = anchor.getBoundingClientRect();
  menu.style.left = `${Math.min(r.left, window.innerWidth - menu.offsetWidth - 12)}px`;
  menu.style.bottom = `${window.innerHeight - r.top + 6}px`;
  menu.querySelectorAll('.perm-menu-item').forEach(it =>
    it.addEventListener('click', () => { setPermMode(it.dataset.v); menu.remove(); }));
  setTimeout(() => document.addEventListener('click', function h(e) {
    if (!menu.contains(e.target) && e.target !== anchor) { menu.remove(); document.removeEventListener('click', h); }
  }), 0);
}

function _openEffortMenu(anchor) {
  document.getElementById('perm-menu')?.remove();
  const cur = getEffort();
  const opts = [
    ['low',    'low',    'quick & minimal — fewer turns'],
    ['medium', 'medium', 'balanced (default)'],
    ['high',   'high',   'thorough — more turns, deeper checks'],
  ];
  const menu = document.createElement('div');
  menu.id = 'perm-menu';
  menu.className = 'perm-menu';
  menu.innerHTML = opts.map(([v, label, desc]) =>
    `<div class="perm-menu-item${v === cur ? ' active' : ''}" data-v="${v}">
       <div class="perm-menu-label">${label}</div>
       <div class="perm-menu-desc">${desc}</div>
     </div>`).join('');
  document.body.appendChild(menu);
  const r = anchor.getBoundingClientRect();
  menu.style.left = `${Math.min(r.left, window.innerWidth - menu.offsetWidth - 12)}px`;
  menu.style.bottom = `${window.innerHeight - r.top + 6}px`;
  menu.querySelectorAll('.perm-menu-item').forEach(it =>
    it.addEventListener('click', () => { setEffort(it.dataset.v); menu.remove(); }));
  setTimeout(() => document.addEventListener('click', function h(e) {
    if (!menu.contains(e.target) && e.target !== anchor) { menu.remove(); document.removeEventListener('click', h); }
  }), 0);
}

function toggleTheme() {
  const root = document.documentElement;
  if (root.dataset.theme === 'light') {
    delete root.dataset.theme; localStorage.removeItem('aide-theme');
  } else {
    root.dataset.theme = 'light'; localStorage.setItem('aide-theme', 'light');
  }
}

// appearance (theme + accent) is stored server-side too, so it's the same on every
// subdomain. localStorage stays as the instant pre-paint cache (see index.html head).
async function _syncAppearance() {
  let s;
  try { s = await fetch('/api/settings').then(r => r.json()); } catch { return; }
  const root = document.documentElement;
  if ('theme' in s) {
    if (s.theme === 'light') { root.dataset.theme = 'light'; localStorage.setItem('aide-theme', 'light'); }
    else { delete root.dataset.theme; localStorage.removeItem('aide-theme'); }
  }
  if ('accent' in s) {
    if (s.accent) { root.style.setProperty('--accent', s.accent); localStorage.setItem('aide-accent', s.accent); }
    else { root.style.removeProperty('--accent'); localStorage.removeItem('aide-accent'); }
  }
}

// ── model picker ──────────────────────────────────────────────────────────────
let _modelModalInited = false;
function openModelModal() {
  document.getElementById('model-modal').style.display = 'flex';
  if (!_modelModalInited) { initModelModal(); _modelModalInited = true; }
  // make sure models tab is active
  document.querySelector('.mm-tab[data-tab="models"]')?.click();
  renderModelList();
  const inp = document.getElementById('model-search-input');
  if (inp) { inp.value = ''; inp.focus(); }
}

// ── persona picker ────────────────────────────────────────────────────────────
let _personas = [];

// transient accent override: a persona can re-theme the app's one accent while it's
// active. NOT persisted — reverts to the user's global accent when you switch away.
export function applyPersonaAccent(hex) {
  const root = document.documentElement;
  if (hex) { root.style.setProperty('--accent', hex); return; }
  const u = localStorage.getItem('aide-accent');
  if (u) root.style.setProperty('--accent', u);
  else root.style.removeProperty('--accent');
}
window._applyPersonaAccent = applyPersonaAccent;

export async function refreshPersonaBtn() {
  try { _personas = await fetch('/api/personas').then(r => r.json()); } catch { return; }
  const btn   = document.getElementById('persona-btn');
  const label = document.getElementById('persona-label');
  const session = window._currentSession;
  if (!session) { btn.style.display = 'none'; applyPersonaAccent(null); return; }
  const active = _personas.find(p => p.id === session.persona_id) || _personas.find(p => p.is_default);
  if (active) {
    btn.style.display = 'flex'; label.textContent = active.name;
  } else if (_personas.length > 0) {
    btn.style.display = 'flex'; label.textContent = 'no persona';
  } else {
    btn.style.display = 'none';
  }
  applyPersonaAccent(active?.accent || null);
}

window._refreshPersonaBtn = refreshPersonaBtn;

async function openPersonaPicker() {
  if (!_personas.length) _personas = await fetch('/api/personas').then(r => r.json());
  const session = window._currentSession;
  if (!session) return;
  const existing = document.getElementById('_persona_picker');
  if (existing) { existing.remove(); return; }
  const picker = document.createElement('div');
  picker.id = '_persona_picker';
  picker.className = 'ctx-menu';
  picker.style.cssText = 'display:block;top:50px;left:260px;min-width:160px';
  const none = document.createElement('div');
  none.className = 'ctx-item'; none.textContent = '— none';
  none.addEventListener('click', async () => {
    await fetch(`/api/sessions/${session.id}`, {
      method: 'PATCH', headers: {'content-type':'application/json'},
      body: JSON.stringify({ persona_id: '' }),
    });
    window._currentSession.persona_id = null; refreshPersonaBtn(); picker.remove();
  });
  picker.appendChild(none);
  for (const p of _personas) {
    const item = document.createElement('div');
    item.className = 'ctx-item'; item.textContent = p.name;
    item.addEventListener('click', async () => {
      await fetch(`/api/sessions/${session.id}`, {
        method: 'PATCH', headers: {'content-type':'application/json'},
        body: JSON.stringify({ persona_id: p.id }),
      });
      window._currentSession.persona_id = p.id;
      toast(`persona set: ${p.name}`, 'success'); refreshPersonaBtn(); picker.remove();
    });
    picker.appendChild(item);
  }
  document.body.appendChild(picker);
  setTimeout(() => document.addEventListener('click', () => picker.remove(), { once: true }), 0);
}

// ── shell prompt ──────────────────────────────────────────────────────────────
function openShellPanel() {
  const panel = document.getElementById('shell-panel');
  if (!panel) return;
  const willOpen = panel.hidden;
  panel.hidden = !willOpen;
  document.getElementById('shell-btn-tool')?.classList.toggle('active', willOpen);
  if (willOpen) document.getElementById('shell-input')?.focus();
}

function closeShellPanel() {
  const panel = document.getElementById('shell-panel');
  if (!panel) return;
  panel.hidden = true;
  document.getElementById('shell-btn-tool')?.classList.remove('active');
}

function submitShellPanel() {
  const input = document.getElementById('shell-input');
  const command = input?.value.trim();
  if (!command) { toast('shell command required', 'error'); return; }
  input.value = '';
  closeShellPanel();
  const message = `\`\`\`sh\n${command}\n\`\`\``;
  if (isResearchMode()) runResearch(message);
  else sendMessage(message);
}

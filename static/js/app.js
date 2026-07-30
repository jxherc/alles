import { initSessions, newChat, createSession, renderSidebar, downloadSession, getActiveId, saveDraft, clearDraft } from './sessions.js';
import { loadModels, renderModelList, renderSidebarModelList, getSelected, getCurrentEndpoint, initModelModal, prettyModel, restoreSessionModel, selectAideDefault, selectPersonaModel } from './models.js?v=212';
import { populateDropdown } from './dropdown.js?v=212';
import { icon, iconEl, ICON_NAMES } from './icons.js';
// expose globally so the inline-HTML modules can call icon() without each importing it
window.icon = icon; window.iconEl = iconEl; window.ICON_NAMES = ICON_NAMES;
import { chooseBootState } from './bootstate.js';
import { activeAfterlifeSpaces, loadAfterlifeFeatures } from './afterlife.js';
import { providerKey } from './brandlogo.js';
import { canSendMessage, sendMessage, stopStream, hideConnBanner } from './chat.js';
import { toast, closeAllModals, mdToHtml, api } from './util.js';
import { loadTasks, addTask } from './tasks.js';
import { loadCalendar, newEvent } from './calendar.js';
import { loadGallery, initGalleryUpload } from './gallery.js';
import { initSlash, tryExecuteSlashCommand } from './slash.js?v=283';
import { attachFile, discardAttachments, initDropZone } from './uploads.js?v=253';
import { loadProjects } from './projects.js';
import { openSearch, closeSearch, initSearch } from './search.js';
import { initCompareView, loadCompareModels, loadCompareLeaderboard } from './compare.js';
import { loadVaultView, initVault } from './vault.js?v=282';
import { loadContacts, addContact } from './contacts.js';
import { loadFiles, initFiles } from './filesphase7.js?v=273';
import { loadMail, startMailPoll } from './mail.js';
import { initAppCogs } from './appsettings.js';
import { loadPhotos, initPhotos } from './photos.js';
import { setBaseDomain, parseHost, appForSub, viewToSub, urlForApp, currentSub, singleHost, SUBDOMAIN_VIEWS, shouldPollModels } from './subdomain.js?v=237';
import { buildCompatibilityUrl, resolveCompatibilityRoute } from './routecompat.js?v=237';
import { GROUP_DEFINITIONS, groupIdentifierFor, groupRouteFor, initSpecialistGroup, releaseSpecialistLegacyView } from './specialist_groups.js?v=5';
import { addSsoAuthCode, buildApexBrokerUrl, normalizeSsoTarget, stripTransientParams } from './sso-state.js';
import { loadBrainPanel } from './brain.js?v=241';
import { openSettings, closeSettings, applyVis } from './settings.js?v=289';
import {
  setIncognitoMode,
  getPermMode,
  setPermMode,
  getEffort,
  setEffort,
  getReasoningMode,
  setReasoningMode,
  getCustomEffort,
  setCustomEffort,
  permLabel,
  effortLabel,
} from './modes.js?v=256';
import { initPrivacyHandlers } from './privacy.js';
import { initScrollFollow } from './scrollfollow.js';
import { initAideWorkspace } from './aideworkspace.js?v=276';
import { beginBusy, createFocusBoundary, initKokuenPrimitives, setControlState } from './kokuen.js?v=1';
import { validatedProjectId, withProjectContext } from './andromeda.js?v=247';
import { loadShortcuts, matchesShortcut, matchesSettingsShortcut } from './shortcuts.js';
import { startReminderPoll, initReminderPanel } from './reminders.js?v=243';
import { registerServiceWorker } from './push.js';
import { initSync } from './sync.js';
import { cachedLocalizationSettings, configureLocalization, formatDate, formatDateTime, formatTime, prepareLocalization, t } from './i18n.js';
import { cancelRecording as cancelVoiceRecording, isRecording as isVoiceRecording } from './voice.js';

window._mdToHtml = mdToHtml;
initKokuenPrimitives(document);

// ── init ──────────────────────────────────────────────────────────────────────
// single sign-on: log in once at alles and every app subdomain unlocks. cookies
// can't be shared across *.localhost, so an unauthed app silently bounces through
// the apex (which holds the session) to mint its own — even on a direct visit.
let _pendingSso = null;
let _pendingContextHandoffCode = '';
let _pendingContextHandoffPayload = null;
const CONTEXT_HANDOFF_STORAGE_KEY = 'alles.pendingContextHandoff';
const CONTEXT_HANDOFF_PAYLOAD_STORAGE_KEY = 'alles.pendingContextHandoffPayload';
let _afterlifeFlags = {};
let _authEnabled = false;

async function init() {
  const params = new URLSearchParams(location.search);
  // 1. redeem a handoff code if an app/the apex sent us one
  const code = params.get('_auth');
  let redeemedAuthCode = false;
  if (code) {
    try {
      const response = await fetch('/api/auth/redeem?code=' + encodeURIComponent(code));
      redeemedAuthCode = response.ok;
    } catch {}
    _stripParam('_auth');
  }

  let me = {};
  let reachable = true;
  try {
    me = await fetch('/api/auth/me').then(r => r.json());
    setBaseDomain(me.base_domain);
    localStorage.setItem('alles_auth_cache', JSON.stringify(me));   // remember for offline
  } catch {
    // 11b: offline → trust the last known session so the installed PWA still opens
    reachable = false;
    try { me = JSON.parse(localStorage.getItem('alles_auth_cache') || '{}'); } catch {}
    if (me.base_domain) setBaseDomain(me.base_domain);
  }
  _authEnabled = me.enabled === true;

  // server unreachable + nothing cached → say "not running", don't bounce to a dead login wall
  if (chooseBootState(reachable, me.authenticated) === 'notrunning') { _showNotRunning(); return; }

  // 2. apex acting as the SSO broker: an app bounced here (?_sso=app.host) for a session
  const ssoTarget = params.get('_sso');
  if (ssoTarget) {
    const target = _validSsoTarget(ssoTarget);
    if (me.authenticated && target) { _ssoRedirect(target); return; }
    if (!me.authenticated) {
      _pendingSso = target;
      if (!target) _stripParam('_sso');
      _showLoginScreen();
      return;
    }
    _stripParam('_sso');   // authed but a junk target → ignore, continue to the hub
  }

  // 3. not authed here → bounce to the apex ONCE to pick up an existing session
  if (!me.authenticated) {
    if (parseHost().sub && !redeemedAuthCode) {
      try { location.replace(buildApexBrokerUrl(location.href, parseHost().base)); }
      catch { _showLoginScreen(); }
      return;
    }
    _showLoginScreen();
    return;
  }
  await _boot({ reachable });
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
    const response = await fetch('/api/auth/handoff');
    if (!response.ok) throw new Error('handoff failed');
    const { code } = await response.json();
    location.replace(addSsoAuthCode(target, code));
  } catch { _stripParam('_sso'); _showLoginScreen(); }
}

function _storedContextHandoffCode() {
  try { return sessionStorage.getItem(CONTEXT_HANDOFF_STORAGE_KEY) || ''; }
  catch { return ''; }
}

function _rememberContextHandoffCode(code) {
  try { sessionStorage.setItem(CONTEXT_HANDOFF_STORAGE_KEY, code); } catch {}
}

function _forgetContextHandoffCode() {
  try { sessionStorage.removeItem(CONTEXT_HANDOFF_STORAGE_KEY); } catch {}
}

function _storedContextHandoffPayload() {
  try {
    const payload = JSON.parse(sessionStorage.getItem(CONTEXT_HANDOFF_PAYLOAD_STORAGE_KEY) || 'null');
    return payload && typeof payload === 'object' && typeof payload.ask === 'string' ? payload : null;
  } catch { return null; }
}

function _rememberContextHandoffPayload(payload) {
  try { sessionStorage.setItem(CONTEXT_HANDOFF_PAYLOAD_STORAGE_KEY, JSON.stringify(payload)); } catch {}
}

function _discardContextHandoff() {
  _pendingContextHandoffCode = '';
  _pendingContextHandoffPayload = null;
  _forgetContextHandoffCode();
  try { sessionStorage.removeItem(CONTEXT_HANDOFF_PAYLOAD_STORAGE_KEY); } catch {}
}

function _isTerminalContextHandoffError(error) {
  return [400, 404, 410, 422].includes(Number(error?.status));
}

async function _redeemPendingContextHandoff() {
  if (_pendingContextHandoffPayload) return _pendingContextHandoffPayload;
  if (!_pendingContextHandoffCode) return null;
  const response = await fetch(
    `/api/auth/context-handoff/${encodeURIComponent(_pendingContextHandoffCode)}`,
    { method: 'POST', cache: 'no-store' },
  );
  if (!response.ok) {
    const error = new Error('context handoff unavailable');
    error.status = response.status;
    throw error;
  }
  const payload = await response.json();
  _pendingContextHandoffPayload = payload;
  _rememberContextHandoffPayload(payload);
  _pendingContextHandoffCode = '';
  _forgetContextHandoffCode();
  return payload;
}

function _showContextHandoffRetry(projectId = '') {
  if (!_pendingContextHandoffCode && !_pendingContextHandoffPayload) return;
  const container = document.getElementById('toast-container');
  if (!container) return;
  document.getElementById('context-handoff-error')?.remove();
  const notice = document.createElement('div');
  notice.id = 'context-handoff-error';
  notice.className = 'toast error context-handoff-error';
  notice.setAttribute('role', 'alert');
  const message = document.createElement('span');
  message.textContent = 'private document context could not be opened';
  const retry = document.createElement('button');
  retry.type = 'button';
  retry.textContent = 'retry';
  retry.addEventListener('click', async () => {
    if (!_pendingContextHandoffCode && !_pendingContextHandoffPayload) { notice.remove(); return; }
    retry.disabled = true;
    message.textContent = 'retrying private document context';
    try {
      const payload = await _redeemPendingContextHandoff();
      const ask = String(payload?.ask || '');
      if (ask) {
        const delivered = await window._askInChat(
          ask,
          payload.web === true,
          payload.document_scope || null,
          projectId,
          true,
        );
        if (!delivered) throw new Error('context handoff was not accepted');
      }
      _discardContextHandoff();
      notice.remove();
    } catch (error) {
      if (_isTerminalContextHandoffError(error)) {
        _discardContextHandoff();
        message.textContent = 'private document context expired';
        retry.textContent = 'dismiss';
      } else {
        message.textContent = 'private document context is still unavailable';
      }
      retry.disabled = false;
      retry.focus();
    }
  });
  notice.append(message, retry);
  container.appendChild(notice);
}

// only relay a session to OUR own app subdomains (no open-redirect / token leak)
function _validSsoTarget(target) {
  const { base, port } = parseHost();
  return normalizeSsoTarget(target, {
    protocol: location.protocol,
    port,
    baseDomain: base,
    allowedSubdomains: Object.keys(SUBDOMAIN_VIEWS).filter(Boolean),
  });
}

async function _boot({ reachable = true } = {}) {
  const afterlifeFlags = await loadAfterlifeFeatures();
  _afterlifeFlags = afterlifeFlags;
  const bootParams = new URLSearchParams(location.search);
  const handoffProjectId = validatedProjectId(bootParams.get('project_id'));
  let handoffAsk = bootParams.get('ask') || '';
  let handoffWeb = bootParams.get('web') === '1';
  let handoffDocumentScope = null;
  const urlContextCode = bootParams.get('ctx') || '';
  const contextCode = urlContextCode || _storedContextHandoffCode();
  const storedContextPayload = urlContextCode ? null : _storedContextHandoffPayload();
  let contextHandoffFailed = false;
  _consumeParams(['ask', 'web']);
  if (contextCode || storedContextPayload) {
    _pendingContextHandoffPayload = storedContextPayload;
    _pendingContextHandoffCode = contextCode;
    if (urlContextCode) {
      try { sessionStorage.removeItem(CONTEXT_HANDOFF_PAYLOAD_STORAGE_KEY); } catch {}
      _rememberContextHandoffCode(contextCode);
      _stripParam('ctx');
    }
    try {
      const payload = await _redeemPendingContextHandoff();
      handoffAsk = String(payload.ask || '');
      handoffWeb = payload.web === true;
      handoffDocumentScope = payload.document_scope || null;
    } catch (error) {
      handoffDocumentScope = null;
      if (_isTerminalContextHandoffError(error)) {
        _discardContextHandoff();
        if (urlContextCode) handoffAsk = '';
      } else {
        handoffAsk = '';
        contextHandoffFailed = true;
      }
    }
  }
  const hasPriorityAction = !!(handoffAsk || bootParams.get('mailoauth'));
  const initialRoute = resolveCompatibilityRoute({
    sub: parseHost().sub,
    app: hasPriorityAction ? undefined : bootParams.get('app'),
    view: hasPriorityAction ? undefined : bootParams.get('view'),
    flags: afterlifeFlags,
  });

  if (initialRoute && reachable && !singleHost() && initialRoute.host !== currentSub()) {
    const target = buildCompatibilityUrl({
      currentUrl: location.href,
      route: initialRoute,
      baseDomain: parseHost().base,
    });
    if (target) { await _navigateWithHandoff(target, { replace: true }); return; }
  }

  if (initialRoute) {
    const groupedRoute = groupRouteFor(initialRoute.hashOwner);
    const groupedDeepLink = !!groupedRoute;
    const groupedIdentifier = groupedRoute
      ? groupIdentifierFor(groupedRoute.group, groupedRoute.section)
      : '';
    if (singleHost()) {
      if (groupedDeepLink) {
        _syncSpecialistGroupUrl(initialRoute, groupedIdentifier);
        _consumeParams(['_auth', '_sso']);
      } else {
        _consumeParams(['app', 'view', '_auth', '_sso']);
      }
    } else if (initialRoute.host === currentSub()) {
      if (groupedDeepLink) {
        _syncSpecialistGroupUrl(initialRoute, groupedIdentifier);
        _consumeParams(['_auth', '_sso']);
      } else {
        const cleaned = buildCompatibilityUrl({
          currentUrl: location.href,
          route: initialRoute,
          baseDomain: parseHost().base,
        });
        if (cleaned) _replaceHistoryUrl(cleaned);
      }
    } else {
      // Offline aliases still open their feature in place. Only routing keys are
      // consumed; Files filters, Docs hashes, and other app state stay intact.
      _consumeParams(['app', 'view', '_auth', '_sso']);
    }
  }

  applyVis();
  initAfterlifeShell(afterlifeFlags);
  let bootSettings = {};
  try {
    bootSettings = await fetch('/api/settings').then(r => r.json());
    await prepareLocalization(bootSettings);
  } catch {
    const cachedSettings = cachedLocalizationSettings();
    if (cachedSettings.language) await prepareLocalization(cachedSettings);
    else configureLocalization();
  }
  initScrollFollow();
  _syncAppearance();   // pull theme/accent from the server so it matches across subdomains
  const aideSidebarMedia = window.matchMedia('(max-width: 700px)');
  let aideSidebarWasMobile = aideSidebarMedia.matches;
  const storedAideSidebar = localStorage.getItem('aide-sidebar-hidden');
  if (storedAideSidebar === '1'
    || (storedAideSidebar === null && aideSidebarMedia.matches)) {
    document.body.classList.add('sidebar-hidden');
  }
  const syncAideSidebarViewport = event => {
    if (event.matches && !aideSidebarWasMobile) {
      document.body.classList.add('sidebar-hidden');
    }
    aideSidebarWasMobile = event.matches;
  };
  aideSidebarMedia.addEventListener?.('change', syncAideSidebarViewport);
  // these hit the server; offline they'll fail — don't let that abort the shell render (11b)
  try { await loadModels(); } catch {}
  try { await loadProjects(); } catch {}
  const defaultHashOwner = appForSub(parseHost().sub).primary === 'chat' ? 'session' : 'app';
  try { await initSessions({ hashOwner: initialRoute?.hashOwner || defaultHashOwner }); } catch {}
  const ta = document.getElementById('composer-ta');
  initSlash(ta);
  try { const { initMentions } = await import('./mentions.js'); initMentions(ta); } catch {}
  initSearch();
  initDropZone();
  initVault();
  initPrivacyHandlers();
  startReminderPoll();
  registerServiceWorker();
  initSync();
  bindEvents();
  // per-app settings gears (header cogs) + the reload hooks they call after saving
  initAppCogs();
  window._reloadFiles = () => loadFiles('');   // jump to the (possibly new) root
  window._reloadPhotos = loadPhotos;
  window._reloadCalendar = () => loadCalendar();
  window._reloadMail = startMailPoll;
  window._reloadSystem = () => import('./system.js?v=261').then(m => m.initSystem());
  applySubdomainScope(initialRoute);

  // arrived from another subapp's palette "ask aide / research" → run it once
  const _p = new URLSearchParams(location.search);
  const _ask = handoffAsk;
  if (_ask) {
    const contextHandoffReady = Boolean(_pendingContextHandoffPayload);
    setTimeout(async () => {
      try {
        const delivered = await window._askInChat(
          _ask,
          handoffWeb,
          handoffDocumentScope,
          handoffProjectId,
          contextHandoffReady,
        );
        if (contextHandoffReady) {
          if (!delivered) throw new Error('context handoff was not accepted');
          _discardContextHandoff();
        }
      } catch {
        if (contextHandoffReady) _showContextHandoffRetry(handoffProjectId);
      }
    }, 350);
  }
  if (contextHandoffFailed) {
    setTimeout(() => _showContextHandoffRetry(handoffProjectId), 350);
  }

  // bounced back from the google sign-in flow → report + open mail
  const _mo = _p.get('mailoauth');
  if (_mo) {
    _consumeParams(['mailoauth']);
    const msg = {
      ok: 'gmail connected ✓', denied: 'google sign-in cancelled',
      badstate: 'sign-in expired, try again', failed: "couldn't reach google, try again",
      noemail: "couldn't read your email from google",
    }[_mo] || 'google sign-in finished';
    setTimeout(() => { toast(msg, _mo === 'ok' ? 'success' : 'error'); navigateTo('mail'); }, 300);
  }

  const _v = _p.get('app') || _p.get('view');
  if (_v && !_ask && !_mo && /^[a-z0-9_-]+$/i.test(_v)) {
    _consumeParams(groupRouteFor(_v) ? ['app'] : ['app', 'view']);
    setTimeout(() => navigateTo(_v), 0);
  }
}

function _replaceHistoryUrl(target) {
  const url = new URL(target, location.href);
  history.replaceState(null, '', url.pathname + url.search + url.hash);
}

function _consumeParams(names) {
  try { _replaceHistoryUrl(stripTransientParams(location.href, names)); }
  catch {}
}

async function _navigateWithHandoff(target, { replace = false, docsPrepared = false } = {}) {
  if (!docsPrepared && typeof window._prepareDocsNavigation === 'function') {
    if (!(await window._prepareDocsNavigation())) return false;
  }
  let destination = target;
  if (_authEnabled) {
    try {
      const response = await fetch('/api/auth/handoff');
      if (response.ok) {
        const { code } = await response.json();
        if (code) destination = addSsoAuthCode(target, code);
      }
    } catch {}
  }
  if (replace) location.replace(destination);
  else location.assign(destination);
  return true;
}

// configure the SPA for whichever subdomain we're on: apex = the hub; an app
// subdomain boots straight into that app with a sidebar scoped to its views.
function applySubdomainScope(initialRoute = null) {
  const { sub } = parseHost();
  const app = appForSub(sub);
  const onAide = app.app === 'aide';
  const onHub = app.app === 'alles';
  const onSubApp = !!sub && !onAide;

  document.body.classList.toggle('is-hub', onHub);
  document.body.classList.toggle('is-aide', onAide);
  document.body.classList.toggle('is-subapp', onSubApp);
  document.body.dataset.app = app.app;
  _setAfterlifeSpace(onAide ? 'aide' : '');
  document.title = onHub ? 'alles' : `${app.app} / alles`;
  renderAppCrumb(app.app, sub);

  // chats + composer chrome belong to aide only
  _show('sidebar-toggle-btn', onAide);
  _show('new-chat-btn', onAide);
  document.querySelector('.search-wrap')?.style.setProperty('display', onAide ? '' : 'none');
  _show('session-list', onAide);
  _show('ai-top-controls', onAide);
  // settings is AI-heavy — keep it inside aide, not bleeding onto mail/docs/etc.
  _show('topbar-settings-btn', onAide);
  _show('incognito-btn', onAide);   // incognito lives in the topbar now, aide-only
  // on aide the logo lives in the sidebar's top-left; elsewhere it's the topbar crumb
  _show('app-crumb', !onAide);
  if (!onAide) {
    _show('persona-btn', false);
    _show('session-actions-btn', false);
  }
  // the sidebar only renders on aide now, so show every nav item there and let
  // applyVis (user prefs) be the only thing that hides any of them.

  // landing
  if (initialRoute) renderLocalRoute(initialRoute);
  else if (!sub) { if (!location.hash) (_afterlifeFlags.afterlife_today ? showTodayView() : showHomeView()); }
  else if (!(app.primary === 'chat' && location.hash)) renderLocalRoute({ view: app.primary, hashOwner: app.primary });
  // (aide with a #sessionId is already restored by initSessions)
  document.body.classList.remove('preboot', 'login-mode');
}

function _show(id, on) { const e = document.getElementById(id); if (e) e.style.display = on ? '' : 'none'; }

function renderAppCrumb(appName, sub) {
  const crumb = document.getElementById('app-crumb');
  if (!crumb) return;
  if (appName === 'alles') {                 // on the hub: just the wordmark, nowhere to go
    crumb.replaceChildren(document.createTextNode('alles'));
    crumb.title = 'home';
    return;
  }
  _buildCrumb(crumb, appName, sub || appName);
}

// A compact local identity link. Global navigation belongs to the universal
// shell control, so the old "app / alles" breadcrumb is intentionally gone.
function _buildCrumb(el, appName, appSub) {
  const appA = document.createElement('a');
  appA.className = 'crumb-app'; appA.textContent = appName;
  appA.href = urlForApp(appSub); appA.title = `open ${appName}`;
  el.replaceChildren(appA);
}

function _wireCrumbNav(el) {
  if (!el || el.dataset.crumbWired) return;
  el.dataset.crumbWired = '1';
  el.addEventListener('click', e => {
    if (e.metaKey || e.ctrlKey || e.shiftKey) return;   // let the browser open a new tab
    // The app-name part keeps native link behavior. Home and cross-app movement
    // live in the shell navigation sheet.
  });
}

// single host (raw ip / no subdomains): there's nowhere to jump to, so we fake the
// per-app chrome (crumb + title) as the user moves between apps in-page.
function _shChrome(v, { onAide = false } = {}) {
  const sub = viewToSub(v);
  const app = appForSub(sub);
  const onHome = !onAide && (v === 'home' || v === 'today');
  document.body.classList.toggle('is-hub', onHome);
  document.body.classList.toggle('is-subapp', !onHome && !onAide);
  document.body.classList.toggle('is-aide', onAide);
  document.body.dataset.app = onAide ? 'aide' : app.app;
  document.title = onHome ? 'alles' : onAide ? 'aide' : `${app.app} / alles`;
  _show('app-crumb', !onHome && !onAide);
  const crumb = document.getElementById('app-crumb');
  if (crumb) {
    if (onHome) crumb.replaceChildren(document.createTextNode('alles'));
    else if (onAide) crumb.replaceChildren(document.createTextNode('aide'));
    else _buildCrumb(crumb, app.app, sub || app.app);
  }
}

// cross-app jump → full-page nav to that app's subdomain, carrying an SSO handoff code
async function crossNav(sub, view = '', { docsPrepared = false } = {}) {
  if (singleHost()) { navigateTo(view || appForSub(sub).primary); return; }  // one origin → in-page
  const targetUrl = new URL(urlForApp(sub));
  if (view === 'andromeda') targetUrl.searchParams.set('app', 'andromeda');
  else if (view && view !== appForSub(sub).primary) targetUrl.searchParams.set('view', view);
  const base = targetUrl.toString();
  const target = view === 'andromeda'
    ? withProjectContext(base, window._currentSession?.project_id)
    : base;
  await _navigateWithHandoff(target, { docsPrepared });
}

function _showNotRunning() {
  document.body.classList.remove('preboot');
  document.body.classList.add('login-mode');
  const screen = document.getElementById('notrunning-screen');
  if (screen) screen.style.display = 'flex';
  const retry = document.getElementById('notrunning-retry');
  if (retry && !retry.dataset.wired) {
    retry.dataset.wired = '1';
    retry.addEventListener('click', () => location.reload());
  }
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
  'today-view', 'andromeda-view', 'home-view', 'chat', 'plan-view', 'inbox-view', 'library-view', 'health-group-view', 'finance-view', 'docs-workbench-view', 'files-workbench-view', 'vault-workbench-view', 'server-workbench-view', 'tasks-view', 'calendar-view', 'gallery-view',
  'models-view', 'brain-view', 'wiki-view', 'compare-view', 'vault-view', 'contacts-view',
  'reminders-view', 'aide-scheduled-view', 'files-view', 'mail-view', 'photos-view', 'subs-view', 'money-view', 'days-view', 'cookbook-view', 'usage-view', 'skills-view', 'activity-view', 'system-view', 'watch-view', 'habits-view', 'read-view', 'books-view', 'health-view',
  'project-view',
];

function hideAllViews() {
  _VIEW_IDS.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
  document.getElementById('composer-outer').style.display = 'none';
}

let _specialistRunId = 0;
const _specialistFetch = window.fetch.bind(window);

// Keep one small, honest state contract around every specialist screen.  App
// modules still own their useful empty and partial content; this layer only
// covers the shared initial load and a fatal backend failure.
async function _trackSpecialistRequest(run, ...args) {
  if (run) run.requests += 1;
  try {
    const response = await _specialistFetch(...args);
    if (run) {
      if (!response.ok) run.failures += 1;
      else run.successes += 1;
    }
    return response;
  } catch (error) {
    if (run) run.failures += 1;
    throw error;
  }
}

function _paintSpecialistState(root, state, retry) {
  if (!root || (!root.dataset.specialistApp && !root.classList.contains('aide-tool-view'))) return;
  let line = root.querySelector(':scope > .specialist-state');
  if (!line) {
    line = document.createElement('div');
    line.className = 'specialist-state';
    line.setAttribute('role', 'status');
    line.setAttribute('aria-live', 'polite');
    root.prepend(line);
  }
  root.setAttribute('aria-busy', state === 'loading' ? 'true' : 'false');
  line.dataset.state = state;
  if (state === 'ready') {
    line.hidden = true;
    line.replaceChildren();
    return;
  }
  line.hidden = false;
  const label = root.dataset.stateLabel || root.dataset.specialistApp || 'page';
  const copy = document.createElement('span');
  copy.textContent = state === 'loading'
    ? `loading ${label}…`
    : state === 'partial'
      ? `some ${label} data is unavailable`
      : `couldn’t load ${label}`;
  line.replaceChildren(copy);
  if (state !== 'loading' && retry) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'specialist-state-retry';
    button.textContent = 'retry';
    button.addEventListener('click', retry, { once: true });
    line.append(button);
  }
}

function showView(viewId, navKey, onShow, stateRootId = '') {
  hideAllViews();
  const root = document.getElementById(viewId);
  root.style.display = 'flex';
  setNav(navKey);
  if (!root.dataset.specialistApp && !root.classList.contains('aide-tool-view')) {
    return onShow?.(callback => callback(), _specialistFetch);
  }

  const stateRoot = stateRootId ? document.getElementById(stateRootId) : root;
  stateRoot.dataset.stateLabel = stateRoot.dataset.specialistApp || navKey;
  const retry = () => showView(viewId, navKey, onShow, stateRootId);
  const run = {
    id: String(++_specialistRunId),
    root: stateRoot,
    requests: 0,
    successes: 0,
    failures: 0,
  };
  stateRoot.dataset.specialistRun = run.id;
  const request = (...args) => _trackSpecialistRequest(run, ...args);
  const track = callback => callback();
  _paintSpecialistState(stateRoot, 'loading', retry);
  let result;
  try {
    result = track(() => onShow?.(track, request));
  } catch {
    _paintSpecialistState(stateRoot, 'error', retry);
    return;
  }
  return Promise.resolve(result).then(() => {
    if (stateRoot.dataset.specialistRun !== run.id) return;
    const state = run.failures && !run.successes
      ? 'error'
      : run.failures
        ? 'partial'
        : 'ready';
    _paintSpecialistState(stateRoot, state, retry);
  }).catch(() => {
    if (stateRoot.dataset.specialistRun !== run.id) return;
    _paintSpecialistState(stateRoot, 'error', retry);
  });
}

async function trackedImport(track, request, load, initialize) {
  const module = await load();
  return track(() => initialize(module, request));
}

const showChatView = () => {
  _setAfterlifeSpace('aide');
  if (singleHost()) _shChrome('chat', { onAide: true });
  hideAllViews();
  document.getElementById('chat').style.display = 'flex';
  document.getElementById('composer-outer').style.display = 'block';
  setNav('chat');
};
// so selectSession (sessions.js) can jump back to chat when a convo is clicked
// from a tools page — otherwise messages render behind the still-open tool view
window._enterChatView = showChatView;
window._newGeneralChat = () => { showChatView(); newChat(); };

// open a project's workspace page (called from the sidebar project folders)
window._openProject = (pid) => showView('project-view', 'project', () => import('./projectview.js').then(m => m.renderProject(pid)));

// the command palette (search.js) reaches across subdomains, so expose the router
// + an "ask aide / Andromeda search" handoff it can call from any app.
window._navigateTo = (v) => navigateTo(v);
window._navigateHome = () => navigateTo(_afterlifeFlags.afterlife_today ? 'today' : 'home');
window._askInChat = async (
  q,
  web = false,
  documentScope = null,
  projectId = '',
  contextHandoffRedeemed = false,
) => {
  q = (q || '').trim();
  if (!q) return false;
  if (web && documentScope && !contextHandoffRedeemed) {
    const target = new URL(urlForApp('andromeda'));
    target.searchParams.set('app', 'andromeda');
    try {
      const response = await fetch('/api/auth/context-handoff', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ask: q, web: true, document_scope: documentScope }),
      });
      if (!response.ok) throw new Error('handoff failed');
      const { code } = await response.json();
      if (!code) throw new Error('handoff failed');
      target.searchParams.set('ctx', code);
      return await _navigateWithHandoff(withProjectContext(
        target.toString(),
        projectId || window._currentSession?.project_id,
      ));
    } catch {
      toast('could not open this in andromeda', 'error');
      return false;
    }
  }
  if (web) {
    const target = `${urlForApp('andromeda')}?app=andromeda&q=${encodeURIComponent(q)}`;
    const canOpenAndromedaInline = singleHost() || appForSub(currentSub()).app === 'andromeda';
    if (canOpenAndromedaInline) {
      if (!(await navigateTo('andromeda'))) return false;
      const scopedProjectId = validatedProjectId(
        projectId || window._currentSession?.project_id,
      );
      if (scopedProjectId && window._currentSession?.project_id !== scopedProjectId) {
        newChat({ projectId: scopedProjectId });
      }
      _replaceHistoryUrl(withProjectContext(location.href, scopedProjectId));
      const module = await import('./andromeda.js?v=247');
      await module.runAndromedaSearch(q, { documentScope });
      return true;
    }
    // _navigateWithHandoff adds the auth code to this complete target URL. If
    // the destination still needs the apex broker, buildApexBrokerUrl carries
    // its complete location.href again, so q and project context survive both
    // authenticated and unauthenticated cross-subdomain paths.
    return _navigateWithHandoff(withProjectContext(
      target,
      projectId || window._currentSession?.project_id,
    ));
  }
  const ta = document.getElementById('composer-ta');
  const canOpenAideInline = singleHost() || appForSub(currentSub()).app === 'aide';
  if (ta && canOpenAideInline) {   // on aide (or one-host installs) — run it inline
    if (!(await navigateTo('chat'))) return false;
    if (projectId && window._currentSession?.project_id !== projectId) newChat({ projectId });
    window._setAideDocumentScope?.(documentScope);
    ta.value = q; ta.dispatchEvent(new Event('input', { bubbles: true }));
    await sendMessage(q);
    return true;
  } else {    // from another subapp — store private context behind a one-time opaque code
    const target = new URL(urlForApp('aide'));
    try {
      const response = await fetch('/api/auth/context-handoff', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ask: q, web, document_scope: documentScope || null }),
      });
      if (!response.ok) throw new Error('handoff failed');
      const { code } = await response.json();
      if (!code) throw new Error('handoff failed');
      target.searchParams.set('ctx', code);
      return await _navigateWithHandoff(withProjectContext(
        target.toString(),
        projectId || window._currentSession?.project_id,
      ));
    } catch {
      toast('could not open this in aide', 'error');
      return false;
    }
  }
};
const showModelsView  = () => showView('models-view',   'models',   () => renderSidebarModelList(document.getElementById('sidebar-model-search')?.value || ''));
const showBrainView   = () => showView('brain-view',    'brain',    (_track, request) => loadBrainPanel(request));
const showTasksView    = () => showView('tasks-view',    'tasks',    (_track, request) => loadTasks(request));
const showCalendarView = () => showView('calendar-view', 'calendar', (_track, request) => loadCalendar(request));
const showGalleryView  = () => showView('gallery-view',  'gallery',  () => { initGalleryUpload(); return loadGallery(); });
const showCompareView  = () => showView('compare-view',  'compare',  () => { initCompareView(); return Promise.all([loadCompareModels(), loadCompareLeaderboard()]); });
const showWikiView     = (section = 'docs') => showView(
  'wiki-view',
  section === 'journal' ? 'journal' : 'wiki',
  (track, request) => trackedImport(track, request, () => import('./docs.js?v=256'), module => module.initDocs(section, request)),
  section === 'journal' ? 'docs-journal-section' : '',
);
const showVaultView      = () => showView('vault-view',      'vault',     (_track, request) => loadVaultView(request));
const showContactsView   = () => showView('contacts-view',  'contacts',  (_track, request) => loadContacts('', request));
const showRemindersView  = () => {
  releaseSpecialistLegacyView('plan', 'reminders');
  return showView('reminders-view', 'aide-reminders', (_track, request) => initReminderPanel(request));
};
const showSubsView       = () => showView('subs-view',      'subs',      (track, request) => trackedImport(track, request, () => import('./subs.js'), module => module.initSubsPanel(request)));
const showMoneyView      = () => showView('money-view',     'money',     (track, request) => trackedImport(track, request, () => import('./money.js'), module => module.initMoneyPanel(request)));
const showDaysView       = () => showView('days-view',      'days',      (track, request) => trackedImport(track, request, () => import('./days.js?v=2'), module => module.initDaysPanel(request)));
const showJournalView    = () => showWikiView('journal');
const showActivityView   = () => showView('activity-view',  'activity',  (track, request) => trackedImport(track, request, () => import('./activity.js'), module => module.initActivity(request)));
const showSystemView     = () => showView('system-view',    'system',    (track, request) => trackedImport(track, request, () => import('./system.js?v=261'), module => module.initSystem(request)));
const showWatchView      = () => showView('watch-view',     'watch',     (track, request) => trackedImport(track, request, () => import('./watch.js'), module => module.initWatch(request)));
const showHabitsView     = () => showView('habits-view',    'habits',    (track, request) => trackedImport(track, request, () => import('./habits.js'), module => module.initHabits(request)));
const showReadView       = () => showView('read-view',      'read',      (track, request) => trackedImport(track, request, () => import('./read.js'), module => module.initRead(request)));
const showBooksView      = () => showView('books-view',     'books',     (track, request) => trackedImport(track, request, () => import('./books.js'), module => module.initBooks(request)));
const showHealthView     = () => showView('health-view',    'health',    (track, request) => trackedImport(track, request, () => import('./health.js'), module => module.initHealth(request)));
const showCookbookView   = () => showView('cookbook-view',  'cookbook',  (track, request) => trackedImport(track, request, () => import('./cookbook.js'), module => module.initCookbook()));
const showSkillsView     = () => showView('skills-view',    'skills',    (track, request) => trackedImport(track, request, () => import('./skills.js'), module => module.initSkills(request)));
const showUsageView      = () => showView('usage-view',     'usage',     (track, request) => trackedImport(track, request, () => import('./usage.js'), module => module.initUsage()));
const showFilesView      = () => showView('files-view',     'files',     (_track, request) => Promise.all([initFiles(request), loadFiles(undefined, request)]));
const showMailView       = () => showView('mail-view',      'mail',      (_track, request) => loadMail(request));
const showPhotosView     = () => showView('photos-view',    'photos',    (_track, request) => { initPhotos(); return loadPhotos(request); });
const showHomeView       = () => { _setAfterlifeSpace(''); showView('home-view', 'home', renderHome); };
const showTodayView      = () => {
  _setAfterlifeSpace('today');
  const result = showView('today-view', 'today', (track, request) => trackedImport(track, request, () => import('./today.js?v=288'), module => module.initToday({ navigate: navigateTo, apps: HOME_PINNABLE_APPS })));
  _renderFirstRun();
  return result;
};
const showAndromedaView  = () => { _setAfterlifeSpace('andromeda'); return showView('andromeda-view', 'andromeda', (track, request) => trackedImport(track, request, () => import('./andromeda.js?v=247'), module => module.initAndromeda())); };
const showAideScheduledView = () => showView('aide-scheduled-view', 'scheduled', (track, request) => trackedImport(
  track,
  request,
  () => import('./aidescheduled.js?v=246'),
  module => module.initAideScheduled(request),
));

async function _loadSpecialistLegacy(group, section, request) {
  if (section === 'calendar') return loadCalendar(request);
  if (section === 'tasks') return loadTasks(request);
  if (section === 'reminders') return initReminderPanel(request);
  if (section === 'days') return import('./days.js?v=2').then(module => module.initDaysPanel(request));
  if (section === 'mail') return loadMail(request);
  if (section === 'contacts') return loadContacts('', request);
  if (section === 'books') return import('./books.js').then(module => module.initBooks(request));
  if (section === 'read') return import('./read.js').then(module => module.initRead(request));
  if (section === 'health') return import('./health.js').then(module => module.initHealth(request));
  if (section === 'habits') return import('./habits.js').then(module => module.initHabits(request));
  if (section === 'money') return import('./money.js').then(module => module.initMoneyPanel(request));
  if (section === 'subs') return import('./subs.js').then(module => module.initSubsPanel(request));
  if (group === 'docs') return import('./docs.js?v=256').then(module => module.initDocs(section === 'journal' ? 'journal' : 'docs', request));
  if (group === 'files' && section === 'files') return Promise.all([initFiles(request), loadFiles(undefined, request)]);
  if (group === 'files' && section === 'gallery') { initPhotos(); return loadPhotos(request); }
  if (group === 'vault') return loadVaultView(request);
  if (group === 'server' && section === 'overview') return import('./system.js?v=262').then(module => module.initSystem(request));
  if (group === 'server' && section === 'activity') return import('./activity.js').then(module => module.initActivity(request));
  if (group === 'server' && section === 'watch') return import('./watch.js').then(module => module.initWatch(request));
}

const showSpecialistGroup = (group, section = 'overview') => showView(
  GROUP_DEFINITIONS[group].rootId,
  group,
  (_track, request) => initSpecialistGroup(group, { section, request, loadLegacy: _loadSpecialistLegacy }),
);

function _syncSpecialistGroupUrl(route, identifier, { replace = true } = {}) {
  try {
    const url = new URL(location.href);
    url.searchParams.delete('app');
    if (route.section || singleHost()) url.searchParams.set('view', identifier);
    else url.searchParams.delete('view');
    const target = url.pathname + url.search + url.hash;
    const current = location.pathname + location.search + location.hash;
    if (target === current) return;
    if (replace) history.replaceState(null, '', target);
    else history.pushState(null, '', target);
  } catch {}
}

// central nav dispatch — used by both the sidebar nav-items and the home tiles
async function navigateTo(v) {
  const staysInDocs = v === 'wiki' || v === 'journal';
  const docsVisible = document.getElementById('wiki-view')?.style.display !== 'none';
  if (!staysInDocs && docsVisible && typeof window._prepareDocsNavigation === 'function') {
    if (!(await window._prepareDocsNavigation())) return false;
  }
  // memory now lives inside settings, not as its own view
  if (v === 'memory') { openSettings('memory'); return true; }
  // Plan owns the legacy reminders identifier. Aide's tool has its own stable
  // route so deep links and reloads never depend on whichever app is visible.
  const grouped = groupRouteFor(v);
  const groupedIdentifier = grouped ? groupIdentifierFor(grouped.group, grouped.section) : v;
  const groupedRoute = grouped ? {
    // Group names usually match their canonical host. Vault is intentionally
    // served from passwords.*, so derive the destination from the canonical
    // identifier instead of manufacturing a legacy vault.* navigation.
    host: viewToSub(groupedIdentifier),
    view: grouped.group,
    ...(grouped.section !== 'overview' ? { section: grouped.section } : {}),
    hashOwner: v,
  } : null;
  // a view that lives on another subdomain → full-page jump (with SSO handoff).
  // on a single host there are no subdomains, so we just render it here instead.
  if (v !== 'settings' && !singleHost()) {
    const dest = groupedRoute?.host ?? viewToSub(v);
    if (dest !== currentSub()) { await crossNav(dest, groupedIdentifier, { docsPrepared: true }); return true; }
  }
  if (groupedRoute) {
    _syncSpecialistGroupUrl(groupedRoute, groupedIdentifier, { replace: false });
    await renderLocalRoute(groupedRoute);
  } else {
    await renderLocalView(v);
  }
  return true;
}

window._navigateSpecialistSection = (group, section) => {
  return navigateTo(groupIdentifierFor(group, section));
};

window.addEventListener('popstate', async () => {
  const url = new URL(location.href);
  const identifier = url.searchParams.get('view') || url.searchParams.get('app');
  const route = resolveCompatibilityRoute({
    sub: parseHost().sub,
    app: url.searchParams.get('app') || undefined,
    view: url.searchParams.get('view') || undefined,
    flags: _afterlifeFlags,
  });
  const nextGroup = groupRouteFor(route?.hashOwner) || groupRouteFor(route?.view) || groupRouteFor(identifier);
  const docsVisible = document.getElementById('docs-workbench-view')?.style.display !== 'none';
  if (docsVisible && nextGroup?.group !== 'docs' && typeof window._prepareDocsNavigation === 'function') {
    if (!(await window._prepareDocsNavigation())) {
      history.forward();
      return;
    }
  }
  if (route) await renderLocalRoute(route);
  else if (nextGroup) await renderLocalView(nextGroup.group, { view: nextGroup.group, section: nextGroup.section });
  else if (singleHost()) (_afterlifeFlags.afterlife_today ? showTodayView() : showHomeView());
});

function renderLocalRoute(route) {
  if (!route) return;
  const grouped = groupRouteFor(route.hashOwner) || groupRouteFor(route.view);
  if (grouped) return renderLocalView(grouped.group, { ...route, view: grouped.group, section: grouped.section });
  return renderLocalView(route.view, route);
}

const AIDE_TOOL_VIEWS = new Set([
  'chat', 'project', 'brain', 'skills', 'scheduled', 'proactive',
  'models', 'compare', 'gallery', 'cookbook', 'usage', 'aide-reminders',
]);

function renderLocalView(v, route = {}) {
  const staysInAide = AIDE_TOOL_VIEWS.has(v);
  _setAfterlifeSpace(staysInAide ? 'aide' : v === 'today' ? 'today' : v === 'andromeda' ? 'andromeda' : '');
  if (singleHost() && v !== 'settings') _shChrome(v, { onAide: staysInAide });
  if      (v === 'today')     showTodayView();
  else if (v === 'andromeda') return showAndromedaView();
  else if (v === 'home')      showHomeView();
  else if (v === 'chat')      showChatView();
  else if (v === 'models')    showModelsView();
  else if (v === 'brain')     showBrainView();
  else if (v === 'plan')      return showSpecialistGroup('plan', route.section);
  else if (v === 'inbox')     return showSpecialistGroup('inbox', route.section);
  else if (v === 'library')   return showSpecialistGroup('library', route.section);
  else if (v === 'finance')   return showSpecialistGroup('finance', route.section);
  else if (v === 'docs')      return showSpecialistGroup('docs', route.section);
  else if (v === 'files')     return showSpecialistGroup('files', route.section);
  else if (v === 'vault')     return showSpecialistGroup('vault', route.section);
  else if (v === 'server')    return showSpecialistGroup('server', route.section);
  else if (v === 'tasks')     showTasksView();
  else if (v === 'calendar')  showCalendarView();
  else if (v === 'gallery')   showGalleryView();
  else if (v === 'wiki')      showWikiView(route.section || 'docs');
  else if (v === 'compare')   showCompareView();
  else if (v === 'contacts')  showContactsView();
  else if (v === 'aide-reminders') showRemindersView();
  else if (v === 'scheduled' || v === 'proactive') return showAideScheduledView();
  else if (v === 'subs')      showSubsView();
  else if (v === 'money')     showMoneyView();
  else if (v === 'days')      showDaysView();
  else if (v === 'journal')   showJournalView();
  else if (v === 'activity')  showActivityView();
  else if (v === 'system')    showSystemView();
  else if (v === 'watch')     showWatchView();
  else if (v === 'habits')    showHabitsView();
  else if (v === 'read')      showReadView();
  else if (v === 'books')     showBooksView();
  else if (v === 'health')    return showSpecialistGroup('health', route.section);
  else if (v === 'cookbook')  showCookbookView();
  else if (v === 'usage')     showUsageView();
  else if (v === 'skills')    showSkillsView();
  else if (v === 'mail')      showMailView();
  else if (v === 'photos')    showPhotosView();
  else if (v === 'settings')  openSettings();
}

// ── launcher tiles ──────────────────────────────────────────────────────────
const _ICON = {
  home: '<path d="M4 10.5 12 4l8 6.5V20h-6v-6h-4v6H4Z"/>',
  andromeda: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 4 4"/><path d="M8 10.5h5M10.5 8v5"/>',
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
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  system: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/>',
  watch: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  habits: '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
  read: '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
  books: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  health: '<path d="M3 12h4l2 5 4-12 2 7h6"/>',
};
const _svg = (k) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${_ICON[k] || ''}</svg>`;

const HOME_TILES = [
  { view: 'chat',     name: 'aide',     desc: 'chat, agent',     icon: 'chat' },
  { view: 'plan',     name: 'plan',     desc: 'calendar, tasks, reminders', icon: 'calendar' },
  { view: 'inbox',    name: 'inbox',    desc: 'mail & contacts', icon: 'mail' },
  { view: 'library',  name: 'library',  desc: 'books & saved reading', icon: 'books' },
  { view: 'health',   name: 'health',   desc: 'logs & habits', icon: 'health' },
  { view: 'finance',  name: 'finance',  desc: 'money & subscriptions', icon: 'money' },
  { view: 'wiki',     name: 'docs',     desc: 'linked notes',    icon: 'notes' },
  { view: 'files',    name: 'files',    desc: 'your files',      icon: 'files' },
  { view: 'photos',   name: 'gallery',  desc: 'photos',          icon: 'photos' },
  { view: 'vault',    name: 'secrets',  desc: 'passwords',       icon: 'secrets' },
  { view: 'days',     name: 'days',     desc: 'countdowns',      icon: 'days' },
  { view: 'journal',  name: 'journal',  desc: 'daily entries',   icon: 'journal' },
  { view: 'activity', name: 'activity', desc: 'everything, lately', icon: 'activity' },
  { view: 'system',   name: 'system',   desc: 'live machine stats', icon: 'system' },
  { view: 'watch',    name: 'watch',    desc: 'uptime & status',  icon: 'watch' },
];

const HOME_PINNABLE_APPS = [
  { view: 'plan', name: 'plan', desc: 'calendar, tasks, and reminders' },
  { view: 'inbox', name: 'inbox', desc: 'mail and contacts' },
  { view: 'wiki', name: 'docs', desc: 'notes and journal' },
  { view: 'files', name: 'files', desc: 'storage and gallery' },
  { view: 'library', name: 'library', desc: 'books and saved reading' },
  { view: 'health', name: 'health', desc: 'history and habits' },
  { view: 'finance', name: 'finance', desc: 'accounts and subscriptions' },
  { view: 'vault', name: 'vault', desc: 'passwords and passkeys' },
  { view: 'system', name: 'server', desc: 'services, backups, and updates' },
];

const SHELL_GROUPS = Object.freeze([
  ['primary spaces', [
    { view: 'today', name: 'home', desc: 'current work and quick capture', icon: 'home' },
    { view: 'chat', name: 'aide', desc: 'conversation and local execution', icon: 'chat' },
    { view: 'andromeda', name: 'andromeda', desc: 'search and grounded answers', icon: 'andromeda' },
  ]],
  ['everyday', [
    { view: 'plan', name: 'plan', desc: 'calendar, tasks, and reminders', icon: 'calendar' },
    { view: 'inbox', name: 'inbox', desc: 'mail and contacts', icon: 'mail' },
    { view: 'wiki', name: 'docs', desc: 'notes and journal', icon: 'notes' },
  ]],
  ['personal', [
    { view: 'files', name: 'files', desc: 'storage and gallery', icon: 'files' },
    { view: 'library', name: 'library', desc: 'books and saved reading', icon: 'books' },
    { view: 'health', name: 'health', desc: 'history and habits', icon: 'health' },
  ]],
  ['manage', [
    { view: 'finance', name: 'finance', desc: 'accounts and subscriptions', icon: 'money' },
    { view: 'vault', name: 'vault', desc: 'passwords and passkeys', icon: 'secrets' },
    { view: 'system', name: 'server', desc: 'services, backups, and updates', icon: 'system' },
  ]],
]);

let _appDrawerFocusBoundary = null;

function initAfterlifeShell(flags) {
  const spaces = activeAfterlifeSpaces(flags);
  const rail = document.getElementById('space-rail');
  document.body.classList.toggle('afterlife-shell', spaces.length > 0);
  document.body.classList.toggle('afterlife-aide-projects', flags.afterlife_aide_projects === true);
  initAideWorkspace();
  if (!rail || !spaces.length) {
    if (rail) rail.hidden = true;
    return;
  }
  rail.hidden = false;
  _setAfterlifeSpace(document.body.classList.contains('is-aide') ? 'aide' : '');
  _renderAppDrawer();

  const drawer = document.getElementById('app-drawer');
  const trigger = document.getElementById('app-drawer-btn');
  if (drawer && trigger) {
    _appDrawerFocusBoundary = createFocusBoundary(drawer, {
      trigger,
      onEscape: closeAppDrawer,
    });
  }
  trigger?.addEventListener('click', () => {
    if (drawer?.hidden === false) closeAppDrawer();
    else openAppDrawer();
  });
  document.getElementById('app-drawer-close')?.addEventListener('click', closeAppDrawer);
  document.getElementById('app-drawer-scrim')?.addEventListener('click', closeAppDrawer);
  document.getElementById('app-drawer-settings')?.addEventListener('click', () => {
    closeAppDrawer();
    openSettings();
  });
}

function _setAfterlifeSpace(space) {
  document.body.dataset.space = space || '';
  window._syncAideNewTaskContext?.(window._currentSession || null);
}

function _renderAppDrawer() {
  const grid = document.getElementById('app-drawer-grid');
  if (!grid || grid.childElementCount) return;
  for (const [label, destinations] of SHELL_GROUPS) {
    const section = document.createElement('section');
    section.className = 'app-drawer-group';
    const heading = document.createElement('h3');
    heading.textContent = label;
    section.appendChild(heading);
    const list = document.createElement('div');
    list.className = 'app-drawer-list';
    for (const destination of destinations) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'app-drawer-item';
      button.dataset.view = destination.view;
      button.innerHTML = `<span class="app-drawer-icon" aria-hidden="true">${_svg(destination.icon)}</span><span><b>${destination.name}</b><small>${destination.desc}</small></span>`;
      button.addEventListener('click', async () => {
        const staysOnPage = singleHost() || viewToSub(destination.view) === currentSub();
        const navigated = await navigateTo(destination.view);
        // For in-page routes, paint the destination before uncovering it. For a
        // subdomain handoff, keep navigation covering the old surface until the
        // new page replaces it.
        if (staysOnPage && navigated) closeAppDrawer();
      });
      list.appendChild(button);
    }
    section.appendChild(list);
    grid.appendChild(section);
  }
}

function openAppDrawer() {
  const drawer = document.getElementById('app-drawer');
  const scrim = document.getElementById('app-drawer-scrim');
  if (!drawer || !scrim) return;
  drawer.hidden = false;
  scrim.hidden = false;
  document.body.classList.add('app-drawer-open');
  document.getElementById('app-drawer-btn')?.setAttribute('aria-expanded', 'true');
  document.querySelector('.main')?.setAttribute('inert', '');
  document.querySelector('.sidebar')?.setAttribute('inert', '');
  _appDrawerFocusBoundary?.activate({
    source: document.getElementById('app-drawer-btn'),
    focus: document.getElementById('app-drawer-close'),
  });
}

function closeAppDrawer() {
  const drawer = document.getElementById('app-drawer');
  const scrim = document.getElementById('app-drawer-scrim');
  if (!drawer || drawer.hidden) return;
  drawer.hidden = true;
  if (scrim) scrim.hidden = true;
  document.body.classList.remove('app-drawer-open');
  document.getElementById('app-drawer-btn')?.setAttribute('aria-expanded', 'false');
  document.querySelector('.main')?.removeAttribute('inert');
  document.querySelector('.sidebar')?.removeAttribute('inert');
  _appDrawerFocusBoundary?.deactivate();
}

// command-palette nav source (the ⌘K search renders a "go to" group from this)
window._navCommands = SHELL_GROUPS.flatMap(([, destinations]) => destinations)
  .map(destination => ({ view: destination.view, label: destination.name, hint: destination.desc }));

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
    const withModels = eps.filter(e => (e.cached_models || e.models || []).length);
    const opts = [];
    for (const e of withModels) for (const m of (e.cached_models || e.models || []))
      // model name + a glowing brand logo (endpoint still in the value)
      opts.push({ value: `${e.id}::${m}`, label: prettyModel(m), icon: providerKey([e.provider, e.name, e.base_url, m].filter(Boolean).join(' ')) });
    if (!opts.length) opts.push({ value: '', label: 'no model' });
    // default to whatever model the app is already on, not the first of a huge list
    const cur = getSelected();
    const want = cur?.model ? `${cur.endpointId || getCurrentEndpoint()?.id}::${cur.model}` : null;
    populateDropdown(sel, opts, opts.some(o => o.value === want) ? want : opts[0].value);
  } catch {}

  document.getElementById('ha-upload')?.addEventListener('click', () => document.getElementById('ha-file')?.click());
  document.getElementById('ha-file')?.addEventListener('change', async e => {
    const f = e.target.files[0]; if (!f) return;
    try { _haAttach = `\n\n[attached ${f.name}]:\n` + (await f.text()).slice(0, 4000); toast(`attached ${f.name}`, 'success'); }
    catch { toast('could not read that file', 'error'); }
  });
  document.getElementById('ha-voice')?.addEventListener('click', async () => {
    try { (await import('./voice.js')).dictateInto?.(inp); }
    catch { toast('voice input lives in the full aide', 'error'); }
  });

  // withDay=true → the "about my day" button: tuck today's summary in front (and ask for a
  // rundown if the box is empty). withDay=false → a plain quick message to aide.
  const ask = async (withDay) => {
    let q = inp.value.trim();
    if (!withDay && !q) return;
    const [eid, model] = (sel.value || '::').split('::');
    if (!eid) { toast('add a model in settings first', 'error'); return; }
    rep.style.display = 'block'; rep.textContent = '…'; send.disabled = true;
    let ctx = '';
    if (withDay) {
      try {
        const d = await fetch('/api/today').then(r => r.json());
        const bits = [];
        if (d.events?.length) bits.push('events: ' + d.events.map(e => `${e.time || 'all-day'} ${e.title}`).join('; '));
        if (d.tasks?.overdue?.length) bits.push('overdue: ' + d.tasks.overdue.map(t => t.title).join('; '));
        if (d.tasks?.due_today?.length) bits.push('due today: ' + d.tasks.due_today.map(t => t.title).join('; '));
        if (d.reminders?.length) bits.push('reminders: ' + d.reminders.map(r => r.text).join('; '));
        if (bits.length) ctx = `(my day so far — ${bits.join(' | ')})\n\n`;
      } catch {}
      if (!q) q = 'how is my day looking? give me a quick rundown.';
    }
    if (!_haSession) {
      _haSession = (await fetch('/api/sessions', { method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name: 'home: ask aide', model, endpoint_id: eid, incognito: true }) }).then(x => x.json())).id;
    }
    let text = '';
    let pendingRender = false;
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
            try {
              const ev = JSON.parse(dd);
              if (ev.delta) {
                text += ev.delta;
                if (!pendingRender) {
                  pendingRender = true;
                  requestAnimationFrame(() => {
                    rep.innerHTML = mdToHtml(text);
                    pendingRender = false;
                  });
                }
              }
            } catch {}
          }
        }
      }
      rep.innerHTML = mdToHtml(text);
    } catch { rep.textContent = 'failed — try again'; }
    send.disabled = false; inp.value = ''; _haAttach = '';
  };
  send.addEventListener('click', () => ask(false));
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); ask(false); } });
  document.getElementById('ha-day')?.addEventListener('click', () => ask(true));
}

// server-owned first-run state resumes across browsers; browser storage never decides completion.
async function _renderFirstRun() {
  const el = document.getElementById('home-firstrun');
  if (el) { el.style.display = 'none'; el.innerHTML = ''; }
  let st;
  try { st = await fetch('/api/setup/status').then(r => r.json()); }
  catch { return; }   // never let this block the launcher
  if (st.setup?.completed || st.setup?.dismissed) return;
  if (document.getElementById('setup-wizard')?.style.display === 'flex') return;
  (await import('./setupwizard.js?v=284')).openSetupWizard({ status: st });
}
// let anything (a settings link, the command palette) re-run the wizard on demand
window._openSetupWizard = async () => (await import('./setupwizard.js?v=284')).openSetupWizard({ resume: true });

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
  document.getElementById('home-settings-btn')?.addEventListener('click', () => openSettings('general', true));
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
const _escT = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

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

  // proactive cards — advisory suggestions aide surfaced on its own
  let cards = [];
  try { cards = await fetch('/api/proactive').then(r => r.json()); } catch {}
  for (const c of (cards || []).slice(0, 4))
    rows.push(`<div class="ht-row ht-card" data-go="${c.link || 'home'}" data-act="${c.id}"><span class="ht-ico">✦</span><span class="ht-body">${_escT(c.title)}${c.body ? ` <span class="ht-sub">- ${_escT(c.body)}</span>` : ''}</span><button class="icon-btn ht-x" data-dismiss="${c.id}" title="dismiss">✕</button></div>`);

  // recents aren't "today" items — when they're all we have, lead with the
  // clear-day note so the strip still reads as a day view
  const scheduled = rows.length;
  for (const doc of (d.recent_docs || []).slice(0, 2))
    row('wiki', '≡', `recent: ${_escT(doc.name)}`);

  const empty = scheduled ? '' : '<div class="ht-empty">nothing scheduled — clear day ✨</div>';
  el.innerHTML = `${empty}${rows.length ? `<div class="ht-rows">${rows.join('')}</div>` : ''}
    <button class="btn" id="ht-ask">ask aide about my day</button>`;
  el.style.display = 'flex';

  el.querySelectorAll('.ht-row').forEach(r => r.addEventListener('click', () => {
    // clicking a proactive card = acting on it -> teaches the feed to favor this card type (1a)
    if (r.dataset.act) fetch(`/api/proactive/${r.dataset.act}/act`, { method: 'POST' }).catch(() => {});
    navigateTo(r.dataset.go);
  }));
  el.querySelectorAll('.ht-x').forEach(b => b.addEventListener('click', async (ev) => {
    ev.stopPropagation();
    try { await fetch(`/api/proactive/${b.dataset.dismiss}/dismiss`, { method: 'POST' }); } catch {}
    b.closest('.ht-row')?.remove();
  }));
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

  if (!el.dataset.wired) {
    el.dataset.wired = '1';
    el.addEventListener('click', () => openSettings('general'));
  }
}

let _homeClockTimer = null;
function _startHomeClock() {
  const tick = () => {
    const el = document.getElementById('home-clock');
    if (!el) return;
    const now = new Date();
    const date = formatDate(now, { weekday: 'long', month: 'long', day: 'numeric' }).toLowerCase();
    const time = formatTime(now, { hour: 'numeric', minute: '2-digit' }).toLowerCase();
    el.textContent = `${date} · ${time}`;
  };
  tick();
  if (!_startHomeClock.localeBound) {
    _startHomeClock.localeBound = true;
    window.addEventListener('alles:localization-change', tick);
  }
  if (!_homeClockTimer) _homeClockTimer = setInterval(tick, 20000);
}

// aide's tools live in the collapsible "tools" group
const _moreViews = new Set(['gallery','brain','models','aide-reminders','subs','days']);

function setNav(view) {
  document.querySelectorAll('.nav-item').forEach(n => {
    n.classList.toggle('active', n.dataset.view === view);
  });
  document.getElementById('aide-scheduled-link')?.classList.toggle('active', view === 'scheduled');
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

  const closeCompactAideSidebar = () => {
    if (window.matchMedia('(max-width: 700px)').matches) {
      document.body.classList.add('sidebar-hidden');
    }
  };

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
    // Enter (incl. Ctrl/Cmd+Enter) sends; Shift+Enter is a newline. stopPropagation so the
    // event doesn't ALSO reach the document-level `send` shortcut and fire doSend twice. (don't
    // exclude ctrl/meta here — the global shortcut is 'Ctrl+Enter' and never matches Cmd+Enter
    // on mac, so excluding metaKey would leave Cmd+Enter dead.)
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.stopPropagation(); doSend(); }
  });
  // dim send when empty (but never while recording — it doubles as the stop)
  const _sendBtn = document.getElementById('send-btn');
  const syncSend = () => { _sendBtn.classList.toggle('is-empty', !ta.value.trim() && !_sendBtn.classList.contains('recording')); };
  ta.addEventListener('input', syncSend);
  ta.addEventListener('input', saveDraft);   // keep the per-convo draft current
  syncSend();
  _sendBtn.addEventListener('click', async () => {
    const { isRecording, stopRecording } = await import('./voice.js');
    if (isRecording()) stopRecording();
    else doSend();
  });
  // Right-click, Shift+F10, or the Context Menu key schedules the message for
  // later. All three paths open the same custom KOKUEN dialog.
  const openSendSchedule = () => {
    const text = ta.value.trim();
    if (!text) { toast('type a message first — then open send later', ''); return; }
    _openSchedulePop(text, ta);
  };
  _sendBtn.addEventListener('contextmenu', e => {
    e.preventDefault();
    openSendSchedule();
  });
  _sendBtn.addEventListener('keydown', e => {
    if (e.key !== 'ContextMenu' && !(e.shiftKey && e.key === 'F10')) return;
    e.preventDefault();
    openSendSchedule();
  });
  document.getElementById('stop-btn').addEventListener('click', stopStream);
  document.getElementById('conn-banner-x')?.addEventListener('click', hideConnBanner);

  document.getElementById('new-chat-btn').addEventListener('click', () => {
    showChatView();
    newChat();   // fresh chat — not persisted until first message
    closeCompactAideSidebar();
  });

  document.getElementById('session-search').addEventListener('input', e => renderSidebar(e.target.value));
  document.getElementById('sidebar-model-search')?.addEventListener('input', e => renderSidebarModelList(e.target.value));
  document.getElementById('models-refresh-btn')?.addEventListener('click', loadModels);
  document.getElementById('brain-refresh-btn')?.addEventListener('click', loadBrainPanel);
  document.getElementById('brain-open-memory-btn')?.addEventListener('click', () => openSettings('memory'));

  document.querySelector('.c-tools')?.addEventListener('click', e => {
    const btn = e.target.closest('button');
    if (!btn) return;
    if (btn.id === 'more-tools-btn') {
      e.preventDefault();
      e.stopPropagation();
      toggleMoreTools();
    }
  });
  // incognito lives in the topbar (next to settings) → enter a fresh incognito chat;
  // the × in the incognito header is the way back out.
  document.getElementById('incognito-btn')?.addEventListener('click', async () => {
    saveDraft();
    await discardAttachments();
    setIncognitoMode(true);
    newChat();
  });
  document.getElementById('incognito-exit')?.addEventListener('click', async () => {
    const sessionId = getActiveId();
    await discardAttachments();
    if (sessionId) await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' }).catch(() => {});
    setIncognitoMode(false);
    newChat({ skipDraft: true });
  });

  document.getElementById('shell-btn-tool')?.addEventListener('click', openShellPanel);
  document.getElementById('shell-panel-close')?.addEventListener('click', closeShellPanel);
  document.getElementById('shell-send-btn')?.addEventListener('click', submitShellPanel);
  document.getElementById('shell-input')?.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      closeShellPanel();
    } else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      submitShellPanel();
    }
  });
  setMode('agent');
  // permission mode button + label
  const permBtn = document.getElementById('perm-mode-btn');
  if (permBtn) {
    setPermMode(getPermMode());   // sets label span + classes (keeps the icon)
    permBtn.addEventListener('click', e => { e.stopPropagation(); _openPermMenu(permBtn); });
  }
  const effortBtn = document.getElementById('effort-btn');
  if (effortBtn) {
    refreshEffortLabel();
    effortBtn.addEventListener('click', e => { e.stopPropagation(); _openEffortMenu(effortBtn); });
  }
  document.getElementById('aide-model-choice')?.addEventListener('click', openModelModal);
  document.getElementById('topbar-settings-btn')?.addEventListener('click', openSettings);
  document.getElementById('files-settings-btn')?.addEventListener('click', () => openSettings());
  const aideToolsButton = document.getElementById('aide-tools-link');
  const aideToolsMenu = document.getElementById('aide-sidebar-menu');
  aideToolsButton?.addEventListener('click', event => {
    event.stopPropagation();
    setAideToolsMenu(aideToolsMenu?.hidden !== false);
  });
  aideToolsMenu?.addEventListener('click', event => {
    event.stopPropagation();
    if (event.target.closest('[role="menuitem"]')) setAideToolsMenu(false);
  });
  aideToolsMenu?.addEventListener('keydown', event => {
    const items = [...aideToolsMenu.querySelectorAll('[role="menuitem"]')];
    const index = items.indexOf(document.activeElement);
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      setAideToolsMenu(false, { restoreFocus: true });
    } else if (items.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      items[(index + step + items.length) % items.length]?.focus();
    } else if (items.length && (event.key === 'Home' || event.key === 'End')) {
      event.preventDefault();
      items[event.key === 'Home' ? 0 : items.length - 1]?.focus();
    }
  });
  document.addEventListener('click', event => {
    if (!event.target.closest('.aide-sidebar-foot')) setAideToolsMenu(false);
  });
  document.getElementById('aide-settings-link')?.addEventListener('click', () => openSettings());
  document.getElementById('aide-scheduled-link')?.addEventListener('click', () => {
    navigateTo('scheduled');
    closeCompactAideSidebar();
  });
  document.getElementById('today-settings')?.addEventListener('click', () => openSettings('home', true));

  // your name → used by aide's greeting (client-only, no server round-trip)
  const nameInput = document.getElementById('s-user-name');
  if (nameInput) {
    nameInput.value = localStorage.getItem('alles-name') || '';
    nameInput.addEventListener('input', () => localStorage.setItem('alles-name', nameInput.value.trim()));
  }
  _wireCrumbNav(document.getElementById('app-crumb'));

  // persona picker
  document.getElementById('persona-btn').addEventListener('click', openPersonaPicker);

  // model picker
  document.getElementById('model-btn').addEventListener('click', openModelModal);
  document.getElementById('model-modal-close').addEventListener('click', closeModelModal);
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
      <div class="ctx-item" data-a="export-md">export markdown</div>
      <div class="ctx-item" data-a="export-html">export html</div>
      <div class="ctx-item" data-a="export-json">export json</div>
      <div class="ctx-item" data-a="export-txt">export text</div>
      <div class="ctx-sep"></div>
      <div class="ctx-item" data-a="share">copy share link</div>
      <div class="ctx-item" data-a="print">print / save pdf</div>
      <div class="ctx-sep"></div>
      <div class="ctx-item" data-a="audio-summary">🔊 audio overview</div>
      <div class="ctx-item" data-a="audio-podcast">🎙 podcast overview</div>`;
    menu.addEventListener('click', e => {
      const a = e.target.closest('.ctx-item')?.dataset.a;
      if (a?.startsWith('export-')) downloadSession(a.slice(7));
      if (a === 'share')  _shareSession();
      if (a === 'print')  _printSession();
      if (a === 'audio-summary') _playAudioOverview('summary');
      if (a === 'audio-podcast') _playAudioOverview('podcast');
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

  // tasks / calendar / gallery
  document.getElementById('cal-new-btn').addEventListener('click', newEvent);
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
  // 10f — reveal live voice if a realtime provider is configured (gated otherwise)
  import('./voice.js').then(m => m.initLiveVoice?.()).catch(() => {});
  document.getElementById('file-input-hidden')?.addEventListener('change', async e => {
    for (const f of e.target.files) await attachFile(f);
    e.target.value = '';
    e.target.accept = '';
  });
  document.getElementById('composer-ta')?.addEventListener('paste', async event => {
    const clipboardItems = [...(event.clipboardData?.items || [])];
    const files = clipboardItems
      .filter(item => item.kind === 'file')
      .map(item => item.getAsFile())
      .filter(Boolean);
    if (!files.length) return;
    if (!clipboardItems.some(item => item.kind === 'string')) event.preventDefault();
    for (const file of files) await attachFile(file);
  });

  // mic
  document.getElementById('mic-btn')?.addEventListener('click', async () => {
    const { isRecording, startRecording, stopRecording } = await import('./voice.js');
    if (isRecording()) stopRecording(); else startRecording();
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !isVoiceRecording()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    cancelVoiceRecording();
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

  // 11b: tapping the dim backdrop closes the phone drawer
  document.getElementById('nav-backdrop')?.addEventListener('click', () => {
    document.body.classList.add('sidebar-hidden');
  });

  // sidebar nav + brand-as-home
  document.querySelectorAll('.nav-item').forEach(el => {
    el.addEventListener('click', () => {
      navigateTo(el.dataset.view);
      // on a phone, a nav tap should also slide the drawer shut
      if (window.matchMedia('(max-width: 700px)').matches) document.body.classList.add('sidebar-hidden');
    });
  });
  // Aide owns its wordmark; Home has a separate quiet footer control.
  const brand = document.getElementById('brand-home');
  if (brand && !document.body.classList.contains('afterlife-aide-projects')) {
    _buildCrumb(brand, 'aide', 'aide');
    _wireCrumbNav(brand);
  }

  // modal overlays close on backdrop click (except settings which manages itself)
  document.querySelectorAll('.modal-overlay:not(#settings-modal):not(#files-preview-modal)').forEach(o => {
    o.addEventListener('click', e => {
      if (e.target !== o) return;
      if (o.id === 'model-modal') closeModelModal();
      else closeAllModals();
    });
  });

  document.addEventListener('keydown', e => {
    const shortcuts = loadShortcuts();
    if (e.key === 'Escape') {
      const filesPreview = document.getElementById('files-preview-modal');
      if (filesPreview?.style.display !== 'none') return;
      // if a reply is streaming, Esc stops it first; otherwise it closes overlays
      const stopBtn = document.getElementById('stop-btn');
      if (stopBtn?.classList.contains('visible')) { stopStream(); return; }
      closeModelModal(); closeAllModals(); closeSettings(); closeSearch(); closeMoreTools(); closeShellPanel(); closeAppDrawer(); closePermMenu(); setAideSidebarSearch(false);
    }
    else if (matchesShortcut(e, shortcuts.focus_input)) {
      const ta = document.getElementById('composer-ta');
      if (ta && ta.offsetParent !== null) { e.preventDefault(); ta.focus(); }
    }
    else if (matchesShortcut(e, shortcuts.search)) { e.preventDefault(); openSearch(); }
    else if (matchesSettingsShortcut(e, shortcuts.settings)) { e.preventDefault(); openSettings(); }
    else if (matchesShortcut(e, shortcuts.sidebar) && document.body.classList.contains('is-aide')) { e.preventDefault(); document.body.classList.toggle('sidebar-hidden'); }
    else if (matchesShortcut(e, shortcuts.new_chat)) { e.preventDefault(); document.getElementById('new-chat-btn')?.click(); }
    else if (matchesShortcut(e, shortcuts.send)) { e.preventDefault(); doSend(); }
  });
  document.addEventListener('click', () => {
    document.getElementById('ctx-menu').style.display = 'none';
    closeMoreTools();
  });
  // share-btn removed — export/share/print now in topbar-session-actions

  // body.is-aide is set after bindEvents on first boot, so decide from the host
  if (shouldPollModels()) setInterval(loadModels, 30000);
}

let _aoPlaying = false;
async function _playAudioOverview(style) {
  const sid = window._currentSession?.id || getActiveId();
  if (!sid) { toast('open a chat first', 'error'); return; }
  if (_aoPlaying) { toast('already generating an overview', 'error'); return; }
  _aoPlaying = true;
  toast(style === 'podcast' ? 'writing a podcast…' : 'writing an overview…', 'info');
  try {
    const r = await fetch('/api/audio-overview', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ session_id: sid, style }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'failed');
    const { segments } = await r.json();
    if (!segments?.length) { toast('nothing to narrate', 'error'); _aoPlaying = false; return; }
    const { speak } = await import('./voice.js');
    // map the two podcast hosts to distinct TTS voices for a bit of contrast
    const voiceFor = spk => spk === 'Sam' ? 'onyx' : (spk === 'Alex' ? 'nova' : 'alloy');
    toast(`playing ${segments.length} segment${segments.length === 1 ? '' : 's'}`, 'success');
    for (const seg of segments) {
      if (!_aoPlaying) break;   // a second invocation / page change cancels
      try { await speak(seg.text, voiceFor(seg.speaker)); } catch { /* keep going */ }
    }
  } catch (e) {
    toast(e.message || 'audio overview failed', 'error');
  }
  _aoPlaying = false;
}

async function _shareSession() {
  const sid = window._currentSession?.id;
  if (!sid) { toast('open a chat first', 'error'); return; }
  try {
    const r = await fetch(`/api/sessions/${sid}/share`, { method: 'POST' });
    const { url } = await r.json();
    const full = location.origin + url;
    await navigator.clipboard.writeText(full);
    toast('share link copied to clipboard', 'success');
  } catch { toast('share failed', 'error'); }
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

function setAideSidebarSearch(open) {
  const input = document.getElementById('session-search');
  if (open) input?.focus();
  else if (input?.value) {
    input.value = '';
    renderSidebar('');
  }
}

function setAideToolsMenu(open, { restoreFocus = false } = {}) {
  const menu = document.getElementById('aide-sidebar-menu');
  const button = document.getElementById('aide-tools-link');
  if (!menu || !button) return;
  menu.hidden = !open;
  button.setAttribute('aria-expanded', String(open));
  if (open) menu.querySelector('[role="menuitem"]')?.focus();
  else if (restoreFocus) button.focus();
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
  menu.setAttribute('role', 'menu');
  menu.innerHTML = `
    <button class="ctx-item" data-tool="upload" type="button" role="menuitem">upload file</button>
    <button class="ctx-item" data-tool="app" type="button" role="menuitem" aria-haspopup="menu" aria-expanded="false">link an app</button>
  `;
  menu.addEventListener('click', e => {
    e.stopPropagation();
    const item = e.target.closest('.ctx-item');
    const tool = item?.dataset.tool;
    const fileInput = document.getElementById('file-input-hidden');
    if (tool === 'upload' && fileInput) {
      fileInput.accept = '';
      fileInput.click();
      closeMoreTools();
    }
    if (tool === 'app') {
      item.setAttribute('aria-expanded', 'true');
      openAppLinkMenu(menu);
    }
  });
  document.body.appendChild(menu);
  btn.setAttribute('aria-expanded', 'true');
  menu.querySelector('button')?.focus();
}

function insertComposerText(text) {
  const ta = document.getElementById('composer-ta');
  if (!ta) return;
  const start = ta.selectionStart ?? ta.value.length;
  const end = ta.selectionEnd ?? start;
  const before = ta.value.slice(0, start);
  const after = ta.value.slice(end);
  const prefix = before && !/\s$/.test(before) ? ' ' : '';
  const suffix = after && !/^\s/.test(after) ? ' ' : '';
  ta.value = `${before}${prefix}${text}${suffix}${after}`;
  const cursor = before.length + prefix.length + text.length + suffix.length;
  ta.focus();
  ta.setSelectionRange(cursor, cursor);
  ta.dispatchEvent(new Event('input', { bubbles: true }));
}

function openAppLinkMenu(parent) {
  parent.querySelector('.app-link-menu')?.remove();
  const submenu = document.createElement('div');
  submenu.className = 'app-link-menu';
  submenu.setAttribute('role', 'menu');
  submenu.setAttribute('aria-label', 'link an app');
  const apps = HOME_TILES
    .filter(app => app.view && app.view !== 'chat')
    .slice(0, 12);
  submenu.innerHTML = apps.map(app =>
    `<button class="ctx-item" data-app-link="${app.view}" type="button" role="menuitem">@${app.name}</button>`,
  ).join('');
  submenu.addEventListener('click', event => {
    event.stopPropagation();
    const view = event.target.closest('[data-app-link]')?.dataset.appLink;
    if (!view) return;
    insertComposerText(`@${view} `);
    closeMoreTools();
  });
  parent.appendChild(submenu);
  submenu.querySelector('button')?.focus();
}

function closeMoreTools() {
  document.getElementById('_more_tools_menu')?.remove();
  document.getElementById('more-tools-btn')?.setAttribute('aria-expanded', 'false');
}

// ── send ──────────────────────────────────────────────────────────────────────
async function doSend() {
  const ta = document.getElementById('composer-ta');
  let text = ta.value.trim();
  if (!text) return;
  if (await tryExecuteSlashCommand(text)) {
    ta.value = ''; ta.style.height = 'auto'; clearDraft();
    return;
  }
  // a cookbook slash command rewrites the composer to its expanded prompt and returns
  // false ("let normal send handle it") — re-read so we send the expansion, not "/name args".
  text = ta.value.trim();
  if (!text) return;
  // Enter can still reach this function while the send button is disabled. Keep the
  // draft intact instead of clearing it and letting sendMessage reject it as busy.
  if (!canSendMessage()) return;
  ta.value = ''; ta.style.height = 'auto'; clearDraft();
  sendMessage(text);
}

// schedule-send dialog (pointer and keyboard context paths on the send button)
async function _openSchedulePop(text, ta) {
  document.querySelector('.schedule-pop')?.remove();
  const pop = document.createElement('div');
  pop.className = 'schedule-pop';
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-labelledby', 'schedule-pop-title');
  pop.innerHTML = `
    <div class="schedule-pop-title" id="schedule-pop-title">send later</div>
    <div class="date-input" id="schedule-when" data-type="datetime" data-ph="when to send"></div>
    <div class="schedule-pop-actions">
      <button class="btn primary" id="schedule-go" type="button">schedule</button>
      <button class="btn" id="schedule-cancel" type="button">cancel</button>
    </div>`;
  document.body.appendChild(pop);
  const trigger = document.getElementById('send-btn');
  const btnRect = trigger.getBoundingClientRect();
  pop.style.right = `${Math.max(8, window.innerWidth - btnRect.right)}px`;
  pop.style.bottom = `${Math.max(8, window.innerHeight - btnRect.top + 8)}px`;
  const { initDatePicker } = await import('./datepick.js');
  const when = pop.querySelector('#schedule-when');
  initDatePicker(when);
  let focusBoundary = null;
  const close = ({ restoreFocus = true } = {}) => {
    document.removeEventListener('click', outside);
    focusBoundary?.deactivate({ restoreFocus });
    pop.remove();
  };
  const outside = e => {
    if (!pop.contains(e.target) && !document.querySelector('.date-panel')?.contains(e.target)) {
      close({ restoreFocus: false });
    }
  };
  focusBoundary = createFocusBoundary(pop, { trigger, onEscape: close });
  focusBoundary.activate({ focus: when, source: trigger });
  setTimeout(() => document.addEventListener('click', outside), 0);
  pop.querySelector('#schedule-cancel').addEventListener('click', close);
  const scheduleButton = pop.querySelector('#schedule-go');
  scheduleButton.addEventListener('click', async () => {
    const at = when.value;
    if (!at) { toast('pick a time', 'error'); return; }
    if (new Date(at) <= new Date()) { toast('that time is in the past', 'error'); return; }
    const finishBusy = beginBusy(scheduleButton, 'scheduling');
    if (!finishBusy) return;
    try {
      let sid = getActiveId();
      if (!sid) {
        const session = await createSession();
        sid = session?.id;
      }
      if (!sid) throw new Error('no session to schedule into');
      const response = await fetch('/api/reminders', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text, trigger_at: at, type: 'message', session_id: sid }),
      });
      if (!response.ok) throw new Error('failed to schedule');
      finishBusy({ state: 'resting', text: 'schedule' });
      ta.value = ''; ta.style.height = 'auto'; ta.dispatchEvent(new Event('input'));
      const whenText = formatDateTime(at, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).toLowerCase();
      toast(t('schedule.confirmed', { when: whenText }), 'success');
      close();
    } catch (error) {
      finishBusy({ state: 'error', text: 'retry schedule' });
      setControlState(scheduleButton, 'error', { message: error?.message || 'failed to schedule' });
      toast(error?.message || 'failed to schedule', 'error');
      when.focus();
    }
  });
}

// ── mode / theme ──────────────────────────────────────────────────────────────
function setMode(m) {
  document.body.dataset.aideMode = 'agent';
  document.querySelector('.composer-box')?.classList.add('agent-mode');
}
window._setMode = setMode;   // so sessions.js can restore a convo's last mode on load

let _permOutsideHandler = null;
let _permAnchor = null;

function closePermMenu(focusAnchor = false) {
  if (_permOutsideHandler) document.removeEventListener('click', _permOutsideHandler);
  _permOutsideHandler = null;
  const menu = document.getElementById('perm-menu');
  menu?.remove();
  document.getElementById('perm-mode-btn')?.setAttribute('aria-expanded', 'false');
  document.getElementById('effort-btn')?.setAttribute('aria-expanded', 'false');
  if (focusAnchor) _permAnchor?.focus();
  _permAnchor = null;
}

function _openPermMenu(anchor) {
  closePermMenu();
  _permAnchor = anchor;
  const cur = getPermMode();
  const opts = [
    ['full_access', permLabel('full_access'), 'no approval; host shell is unrestricted unless sandboxed'],
    ['full_auto', permLabel('full_auto'), 'handle safe work; ask at real risk'],
    ['approve', permLabel('approve'), 'ask before each change'],
    ['plan', permLabel('plan'), 'read-only — just make a plan, change nothing'],
  ];
  const menu = document.createElement('div');
  menu.id = 'perm-menu';
  menu.className = 'perm-menu';
  menu.setAttribute('role', 'menu');
  menu.innerHTML = opts.map(([v, label, desc]) =>
    `<button class="perm-menu-item${v === cur ? ' active' : ''}${v === 'full_access' ? ' warn' : ''}" data-v="${v}" type="button" role="menuitemradio" aria-checked="${v === cur}">
       <div class="perm-menu-label">${label}</div>
       <div class="perm-menu-desc">${desc}</div>
     </button>`).join('');
  document.body.appendChild(menu);
  const r = anchor.getBoundingClientRect();
  menu.style.left = `${Math.min(r.left, window.innerWidth - menu.offsetWidth - 12)}px`;
  menu.style.bottom = `${window.innerHeight - r.top + 6}px`;
  anchor.setAttribute('aria-expanded', 'true');
  const items = [...menu.querySelectorAll('.perm-menu-item')];
  items.forEach(it => it.addEventListener('click', () => { setPermMode(it.dataset.v); closePermMenu(true); }));
  menu.addEventListener('keydown', event => {
    const index = items.indexOf(document.activeElement);
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      closePermMenu(true);
    }
    else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      items[(index + direction + items.length) % items.length]?.focus();
    }
  });
  items.find(item => item.dataset.v === cur)?.focus();
  const outside = event => {
    if (!menu.contains(event.target) && event.target !== anchor) closePermMenu();
  };
  _permOutsideHandler = outside;
  setTimeout(() => {
    if (_permOutsideHandler === outside && menu.isConnected) {
      document.addEventListener('click', outside);
    }
  }, 0);
}

// the effort applies to the CURRENT model and is remembered per model
const _curModelKey = () => getSelected()?.model || '';
function refreshEffortLabel() {
  const el = document.querySelector('#effort-btn .effort-label');
  if (el) el.textContent = effortLabel(getEffort(_curModelKey()));
  const btn = document.getElementById('effort-btn');
  if (btn) {
    const reasoning = getReasoningMode(_curModelKey());
    btn.title = `effort and reasoning for ${_curModelKey() || 'this model'} · reasoning ${reasoning}`;
  }
}
window._refreshEffortLabel = refreshEffortLabel;

function _openEffortMenu(anchor) {
  closePermMenu();
  _permAnchor = anchor;
  const mk = _curModelKey();
  const cur = getEffort(mk);
  const reasoning = getReasoningMode(mk);
  const custom = getCustomEffort(mk);
  const opts = [
    ['low', effortLabel('low'), 'quick & minimal — fewest turns'],
    ['medium', effortLabel('medium'), 'balanced (default)'],
    ['high', effortLabel('high'), 'thorough — more turns'],
    ['xhigh', effortLabel('xhigh'), 'very thorough'],
    ['max', effortLabel('max'), 'maximum turns'],
    ['deep_work', effortLabel('deep_work'), '48 turns · thorough checks · bounded helpers'],
    ['custom', effortLabel('custom'), '1–64 turns · your verification and helper rules'],
  ];
  const reasoningOpts = [
    ['automatic', 'automatic', 'use the model and effort default'],
    ['on', 'on', 'ask the model to reason'],
    ['off', 'off', 'keep model reasoning disabled'],
  ];
  const menu = document.createElement('div');
  menu.id = 'perm-menu';
  menu.className = 'perm-menu effort-menu';
  menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', 'effort and reasoning');
  menu.innerHTML = '<div class="perm-menu-head"></div>' + opts.map(([v, label, desc]) =>
    `<button class="perm-menu-item${v === cur ? ' active' : ''}" data-kind="effort" data-v="${v}" type="button" role="menuitemradio" aria-checked="${v === cur}">
       <div class="perm-menu-label">${label}</div>
       <div class="perm-menu-desc">${desc}</div>
     </button>`).join('') + `
    <div class="effort-custom" ${cur === 'custom' ? '' : 'hidden'}>
      <div class="effort-custom-row">
        <span>turns</span>
        <div class="effort-stepper" role="group" aria-label="custom turn limit">
          <button type="button" data-turn-delta="-1" aria-label="fewer turns">−</button>
          <output>${custom.maxTurns}</output>
          <button type="button" data-turn-delta="1" aria-label="more turns">+</button>
        </div>
      </div>
      <button class="effort-custom-row effort-cycle" type="button" data-custom-key="verification"><span>verification</span><strong>${custom.verification}</strong></button>
      <button class="effort-custom-row effort-cycle" type="button" data-custom-key="delegation"><span>helpers</span><strong>${custom.delegation}</strong></button>
      <button class="effort-custom-row effort-cycle" type="button" data-custom-key="workflows"><span>workflows</span><strong>${custom.workflows}</strong></button>
    </div>
    <div class="perm-menu-section">reasoning</div>
    ${reasoningOpts.map(([v, label, desc]) => `
      <button class="perm-menu-item${v === reasoning ? ' active' : ''}" data-kind="reasoning" data-v="${v}" type="button" role="menuitemradio" aria-checked="${v === reasoning}">
        <div class="perm-menu-label">${label}</div>
        <div class="perm-menu-desc">${desc}</div>
      </button>`).join('')}`;
  menu.querySelector('.perm-menu-head').textContent = `effort · ${mk || 'model'}`;
  document.body.appendChild(menu);
  const r = anchor.getBoundingClientRect();
  const edge = 12;
  const gap = 10;
  const maxLeft = Math.max(edge, window.innerWidth - menu.offsetWidth - edge);
  const left = Math.max(edge, Math.min(r.left, maxLeft));
  const availableAbove = r.top - gap - edge;
  const availableBelow = window.innerHeight - r.bottom - gap - edge;
  const viewportHeight = Math.max(120, window.innerHeight - edge * 2);
  const minimumMenuHeight = Math.min(220, viewportHeight);
  const naturalHeight = menu.scrollHeight;
  const useAbove = availableAbove >= Math.min(naturalHeight, minimumMenuHeight)
    || availableAbove > availableBelow;
  const availableHeight = useAbove ? availableAbove : availableBelow;
  const constrainedHeight = Math.min(viewportHeight, Math.max(0, availableHeight));
  const canStayBesideAnchor = constrainedHeight >= minimumMenuHeight;
  const maxHeight = canStayBesideAnchor ? constrainedHeight : viewportHeight;
  const renderedHeight = Math.min(naturalHeight, maxHeight);
  const top = canStayBesideAnchor
    ? (useAbove ? r.top - gap - renderedHeight : r.bottom + gap)
    : edge;
  menu.style.left = `${left}px`;
  menu.style.top = `${Math.max(edge, Math.min(top, window.innerHeight - renderedHeight - edge))}px`;
  menu.style.maxHeight = `${Math.floor(maxHeight)}px`;
  anchor.setAttribute('aria-expanded', 'true');
  const activeItem = menu.querySelector('.perm-menu-item.active');
  activeItem?.scrollIntoView({ block: 'nearest' });

  const items = [...menu.querySelectorAll('.perm-menu-item')];
  const close = (focusAnchor = false) => {
    closePermMenu(focusAnchor);
  };
  const onOutside = event => {
    if (!menu.contains(event.target) && event.target !== anchor) close();
  };
  items.forEach(item => item.addEventListener('click', () => {
    if (item.dataset.kind === 'reasoning') {
      setReasoningMode(item.dataset.v, mk);
      refreshEffortLabel();
      close(true);
      return;
    }
    setEffort(item.dataset.v, mk);
    refreshEffortLabel();
    if (item.dataset.v === 'custom') {
      close();
      _openEffortMenu(anchor);
    } else close(true);
  }));
  menu.querySelectorAll('[data-turn-delta]').forEach(button => button.addEventListener('click', () => {
    const next = getCustomEffort(mk);
    next.maxTurns += Number(button.dataset.turnDelta || 0);
    setCustomEffort(mk, next);
    menu.querySelector('.effort-stepper output').textContent = getCustomEffort(mk).maxTurns;
  }));
  const cycles = {
    verification: ['quick', 'standard', 'thorough'],
    delegation: ['off', 'auto'],
    workflows: ['off', 'auto'],
  };
  menu.querySelectorAll('[data-custom-key]').forEach(button => button.addEventListener('click', () => {
    const key = button.dataset.customKey;
    const next = getCustomEffort(mk);
    const values = cycles[key];
    next[key] = values[(values.indexOf(next[key]) + 1) % values.length];
    setCustomEffort(mk, next);
    button.querySelector('strong').textContent = getCustomEffort(mk)[key];
  }));
  menu.addEventListener('keydown', event => {
    const index = items.indexOf(document.activeElement);
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close(true);
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      items[(index + direction + items.length) % items.length]?.focus();
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      items[event.key === 'Home' ? 0 : items.length - 1]?.focus();
    }
  });
  items.find(item => item.dataset.v === cur)?.focus();
  _permOutsideHandler = onOutside;
  setTimeout(() => {
    if (_permOutsideHandler === onOutside && menu.isConnected) {
      document.addEventListener('click', onOutside);
    }
  }, 0);
}

// appearance (theme + accent) is stored server-side too, so it's the same on every
// subdomain. localStorage stays as the instant pre-paint cache (see index.html head).
async function _syncAppearance() {
  // the advanced theme engine owns the full appearance object (colors, font, density,
  // background, frosted). it applies the cached theme instantly, then reconciles with
  // the server — and falls back to the legacy theme/accent settings when nothing's saved.
  try { (await import('./theme.js')).initAppearance(); }
  catch { updateFavicon(); }
}

// favicon tracks the appearance: a square box matching the theme bg + the accent dot.
// (sharp square, no radius — matches the site. static favicon.svg is the no-JS fallback.)
function updateFavicon() {
  const root = document.documentElement;
  const accent = (getComputedStyle(root).getPropertyValue('--accent') || '').trim() || '#818cf8';
  const box = root.dataset.theme === 'light' ? '#f4f4f5' : '#0a0a0a';
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" fill="${box}"/><circle cx="16" cy="16" r="7" fill="${accent}"/></svg>`;
  let link = document.querySelector('link[rel="icon"]');
  if (!link) { link = document.createElement('link'); link.rel = 'icon'; document.head.appendChild(link); }
  link.type = 'image/svg+xml';
  link.href = 'data:image/svg+xml,' + encodeURIComponent(svg);
}
window._updateFavicon = updateFavicon;

// ── model picker ──────────────────────────────────────────────────────────────
let _modelModalInited = false;
let _modelModalFocusBoundary = null;
function closeModelModal() {
  const modal = document.getElementById('model-modal');
  if (!modal || modal.style.display === 'none') return;
  modal.style.display = 'none';
  document.querySelectorAll('#model-btn, #aide-model-choice').forEach(button => {
    button.setAttribute('aria-expanded', 'false');
  });
  _modelModalFocusBoundary?.deactivate();
}
window._closeModelModal = closeModelModal;
function openModelModal() {
  const modal = document.getElementById('model-modal');
  modal.style.display = 'flex';
  document.querySelectorAll('#model-btn, #aide-model-choice').forEach(button => {
    button.setAttribute('aria-expanded', 'true');
  });
  if (!_modelModalInited) { initModelModal(); _modelModalInited = true; }
  // make sure models tab is active
  document.querySelector('.mm-tab[data-tab="models"]')?.click();
  renderModelList();
  const inp = document.getElementById('model-search-input');
  if (inp) inp.value = '';
  if (!_modelModalFocusBoundary) {
    _modelModalFocusBoundary = createFocusBoundary(modal, {
      trigger: document.getElementById('model-btn'),
      onEscape: closeModelModal,
    });
  }
  _modelModalFocusBoundary.activate({ focus: inp, source: document.activeElement });
}

// ── persona picker ────────────────────────────────────────────────────────────
let _personas = [];

// transient accent override: a persona can re-theme the app's one accent while it's
// active. NOT persisted — reverts to the user's global accent when you switch away.
export function applyPersonaAccent(hex) {
  const root = document.documentElement;
  if (hex) { root.style.setProperty('--accent', hex); updateFavicon(); return; }
  // revert to the user's global accent — now lives in the appearance object (aide-accent legacy)
  let acc = '';
  try { acc = (JSON.parse(localStorage.getItem('alles-appearance') || '{}').colors || {}).accent || ''; } catch { /* bad json */ }
  acc = acc || localStorage.getItem('aide-accent');
  if (acc) root.style.setProperty('--accent', acc);
  else root.style.removeProperty('--accent');
  updateFavicon();
}
window._applyPersonaAccent = applyPersonaAccent;

export async function refreshPersonaBtn() {
  try { _personas = await fetch('/api/personas').then(r => r.json()); } catch { return; }
  const btn   = document.getElementById('persona-btn');
  const label = document.getElementById('persona-label');
  const session = window._currentSession;
  if (!_personas.length) {
    window._activePersonaModel = '';
    btn.style.display = 'none'; applyPersonaAccent(null); return;
  }
  // on a fresh chat (no session yet) reflect the pending pick so you can choose a persona
  // BEFORE the first message instead of the button just vanishing
  const pid = session ? session.persona_id : window._pendingPersona;
  const active = _personas.find(p => p.id === pid);
  window._activePersonaModel = active?.model || '';
  btn.style.display = 'flex';
  label.textContent = active ? active.name : 'none';
  applyPersonaAccent(active?.accent || null);
  if (session?.model) restoreSessionModel(session);
  else if (active?.model) selectPersonaModel(active.model);
  else selectAideDefault();
}

window._refreshPersonaBtn = refreshPersonaBtn;

async function openPersonaPicker() {
  if (!_personas.length) _personas = await fetch('/api/personas').then(r => r.json());
  if (!_personas.length) return;
  const session = window._currentSession;   // may be null on a fresh chat -> use a pending pick
  const existing = document.getElementById('_persona_picker');
  if (existing) { existing.remove(); return; }
  const setPersona = async (pid) => {
    if (session) {
      await fetch(`/api/sessions/${session.id}`, {
        method: 'PATCH', headers: {'content-type':'application/json'},
        body: JSON.stringify({ persona_id: pid || '' }),
      });
      window._currentSession.persona_id = pid || null;
    } else {
      window._pendingPersona = pid || null;   // applied when the session is created on first send
    }
    refreshPersonaBtn();
  };
  const picker = document.createElement('div');
  picker.id = '_persona_picker';
  picker.className = 'ctx-menu';
  const btn = document.getElementById('persona-btn');
  const rect = btn.getBoundingClientRect();
  picker.style.cssText = `display:block;left:${rect.left}px;top:${rect.bottom + 4}px;min-width:160px`;
  const none = document.createElement('div');
  none.className = 'ctx-item'; none.textContent = '— none';
  none.addEventListener('click', async () => { await setPersona(''); picker.remove(); });
  picker.appendChild(none);
  for (const p of _personas) {
    const item = document.createElement('div');
    item.className = 'ctx-item'; item.textContent = p.name;
    item.addEventListener('click', async () => {
      await setPersona(p.id);
      // a persona's starter message prefills the composer (if empty)
      const ta = document.getElementById('composer-ta');
      if (p.initial_message && ta && !ta.value.trim()) {
        ta.value = p.initial_message; ta.dispatchEvent(new Event('input', { bubbles: true })); ta.focus();
      }
      toast(`persona set: ${p.name}`, 'success'); picker.remove();
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
  sendMessage(message);
}

import { getActiveId, selectSession, setPrimaryConversationUnavailable } from './sessions.js';
import { createFocusBoundary, createMenuController } from './kokuen.js';
import { openAideRun } from './aiderun.js';
import { initAideCodingWorkspace, openAideCodingWorkspace, closeAideCodingWorkspace } from './aidecoding.js';

const $ = id => document.getElementById(id);
const ACTIVE = new Set(['queued', 'running', 'waiting_input', 'waiting_approval', 'paused']);
const stateLabel = state => ({ succeeded: 'completed', cancelled: 'stopped', waiting_input: 'needs your input', waiting_approval: 'needs approval' }[state] || String(state || 'unknown').replaceAll('_', ' '));
let initialized = false;
let primaryId = '';
let panelKind = '';
let panelGeneration = 0;
let panelBoundary;
let archiveBoundary;
let menu;
let jobs = [];
let refreshTimer;
let archiveInert = [];
let panelInert = [];
let openingCall = false;
let callReturnMode = 'conversation';
let callReturnCaptured = false;
const pendingReceipts = new Set();

function node(tag, text, className = '') {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function action(label, callback) {
  const button = node('button', label);
  button.type = 'button';
  button.addEventListener('click', callback);
  return button;
}
async function json(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error('could not load this data');
  return response.json();
}
function restoreInert(records) {
  for (const [element, inert] of records) if (element.isConnected) element.inert = inert;
}
function suspend(elements) {
  return elements.filter(Boolean).map(element => {
    const value = [element, element.inert];
    element.inert = true;
    return value;
  });
}

function syncHistory() {
  const session = window._currentSession;
  if (session?.primary) primaryId = session.id;
  const history = !!session?.id && !(session.primary || session.id === primaryId) && !session.incognito;
  $('aide-history-context').hidden = !history;
  $('aide-history-name').textContent = history ? session.name || 'earlier conversation' : '';
}

export async function openPrimaryConversation({ focus = true, isCurrent = () => true } = {}) {
  closeContext({ restoreFocus: false });
  window._setAideArchiveOpen?.(false);
  const button = $('aide-return-primary');
  button.disabled = true;
  try {
    if (!primaryId) primaryId = (await json('/api/aide/conversation')).id;
    if (!isCurrent()) return false;
    if (!primaryId) throw new Error('missing conversation');
    if (getActiveId() !== primaryId || window._currentSession?.id !== primaryId || window._aidePrimaryUnavailable) {
      if (!await selectSession(primaryId, '', { isCurrent })) {
        if (!isCurrent()) return false;
        throw new Error('conversation unavailable');
      }
    } else window._enterChatView?.();
    if (!isCurrent()) return false;
    await setMode('conversation');
    syncHistory();
    if (focus) $('composer-ta')?.focus();
    return true;
  } catch {
    if (!isCurrent()) return false;
    setPrimaryConversationUnavailable(true);
    return false;
  } finally { button.disabled = false; }
}

async function setMode(mode, { focus = false, restore = false } = {}) {
  document.body.dataset.aideMode = mode;
  $('aide-mode-conversation').setAttribute('aria-pressed', String(mode === 'conversation'));
  $('aide-mode-coding').setAttribute('aria-pressed', String(mode === 'coding'));
  $('aide-call-open').setAttribute('aria-expanded', String(mode === 'call'));
  closeContext({ restoreFocus: false });
  menu?.close({ restoreFocus: false });
  if (mode !== 'call' && !$('aide-call-workspace').hidden) {
    const voice = await import('./livevoice.js?v=2');
    voice.closeLiveVoiceSurface();
  }
  if (mode === 'coding') {
    window._closeAideTools?.();
    window._setAideArchiveOpen?.(false);
    await openAideCodingWorkspace({ refresh: !restore });
  } else closeAideCodingWorkspace();
  if (focus && mode === 'conversation') $('composer-ta')?.focus();
}

function closeContext({ restoreFocus = true } = {}) {
  if (!$('aide-context-overlay') || $('aide-context-overlay').hidden) return;
  ++panelGeneration;
  panelKind = '';
  $('aide-context-overlay').hidden = true;
  $('aide-jobs-open').setAttribute('aria-expanded', 'false');
  restoreInert(panelInert);
  panelInert = [];
  panelBoundary.deactivate({ restoreFocus });
}

function renderFailure(message, retry) {
  const content = $('aide-context-content');
  const status = node('p', message, 'aide-context-empty');
  status.setAttribute('role', 'status');
  content.replaceChildren(status, action('retry', retry));
}

async function showPrimaryFailure() {
  if (!window._aidePrimaryUnavailable || document.body.dataset.space !== 'aide') return;
  await openContext('conversation');
  if (window._aidePrimaryUnavailable && panelKind === 'conversation') {
    renderFailure('could not open your conversation. retry to continue; your draft is unchanged.', openPrimaryConversation);
  }
}

function renderJobs() {
  const content = $('aide-context-content');
  const focusedRun = content.contains(document.activeElement) ? document.activeElement?.dataset.runId : '';
  const focusedAction = content.contains(document.activeElement) ? document.activeElement?.dataset.contextAction : '';
  const rows = [...jobs].sort((a, b) => Number(ACTIVE.has(b.state)) - Number(ACTIVE.has(a.state)));
  content.replaceChildren();
  if (!rows.length) content.append(node('p', 'no background work yet', 'aide-context-empty'));
  for (const run of rows) {
    const button = action('', () => {
      closeContext({ restoreFocus: false });
      void openAideRun(run.id);
    });
    button.className = 'aide-job-row';
    button.dataset.runId = run.id;
    const text = node('span', undefined, 'aide-job-copy');
    text.append(node('span', run.title || 'background work', 'aide-job-title'));
    const detail = run.result_summary || run.safe_error;
    if (detail) text.append(node('span', detail, 'aide-job-summary'));
    const state = node('span', stateLabel(run.state), 'aide-job-state');
    state.dataset.state = run.state;
    button.append(text, state);
    content.append(button);
  }
  const footer = node('div', undefined, 'aide-context-footer');
  const scheduled = action('scheduled work', () => {
    closeContext({ restoreFocus: false });
    $('aide-scheduled-link')?.click();
  });
  scheduled.dataset.contextAction = 'scheduled';
  footer.append(scheduled);
  content.append(footer);
  if (focusedRun) [...content.querySelectorAll('[data-run-id]')].find(row => row.dataset.runId === focusedRun)?.focus();
  else if (focusedAction === 'scheduled') scheduled.focus();
}

async function refreshJobs({ visible = false } = {}) {
  try {
    const items = await json('/api/jarvis/runs?limit=30');
    if (!Array.isArray(items)) throw new Error('invalid work list');
    const previous = new Map(jobs.map(run => [run.id, run.state]));
    for (const run of items) {
      if (run.state === 'succeeded' && ACTIVE.has(previous.get(run.id))) pendingReceipts.add(run.session_id);
    }
    jobs = items;
    const count = jobs.filter(run => ACTIVE.has(run.state)).length;
    $('aide-jobs-count').hidden = !count;
    $('aide-jobs-count').textContent = String(count);
    $('aide-jobs-open').setAttribute('aria-label', count ? `background work, ${count} active` : 'background work');
    if (visible && panelKind === 'jobs') renderJobs();
    const sessionId = getActiveId();
    if (pendingReceipts.has(sessionId)) {
      pendingReceipts.delete(sessionId);
      void window._refreshAideSessionQuietly?.(sessionId);
    }
  } catch {
    if (visible && panelKind === 'jobs') renderFailure('background work is unavailable', () => refreshJobs({ visible: true }));
  } finally {
    clearTimeout(refreshTimer);
    if (document.body.dataset.space === 'aide' && !document.hidden) {
      refreshTimer = setTimeout(() => void refreshJobs({ visible: panelKind === 'jobs' }), jobs.some(run => ACTIVE.has(run.state)) ? 3000 : 30000);
    }
  }
}

function provenance(memory) {
  let kind;
  try { kind = JSON.parse(memory.provenance || '{}').kind; } catch {}
  return ({ owner_request: 'you asked to remember', direct_owner_statement: 'your preference', model_suggestion: 'suggested from conversation' }[kind]
    || memory.source || 'saved memory');
}

async function renderMemory(generation) {
  try {
    const items = await json('/api/memories');
    if (generation !== panelGeneration || panelKind !== 'memory') return;
    if (!Array.isArray(items)) throw new Error('invalid memories');
    const content = $('aide-context-content');
    content.replaceChildren();
    if (!items.length) content.append(node('p', 'no saved memories yet', 'aide-context-empty'));
    for (const memory of items) {
      const item = node('article', undefined, 'aide-memory-row');
      item.append(node('p', memory.text || ''));
      const metadata = [provenance(memory), memory.scope === 'project' ? 'project' : 'global'];
      if (memory.status === 'suggested') metadata.push('needs review');
      if (memory.pinned) metadata.push('pinned');
      item.append(node('span', metadata.join(' · '), 'aide-memory-source'));
      content.append(item);
    }
    const footer = node('div', undefined, 'aide-context-footer');
    footer.append(action('manage memory', () => {
      closeContext({ restoreFocus: false });
      window._navigateTo?.('memory');
    }));
    content.append(footer);
  } catch {
    if (generation === panelGeneration) renderFailure('memory is unavailable', () => renderMemory(generation));
  }
}

async function openContext(kind) {
  menu?.close({ restoreFocus: false });
  window._setAideArchiveOpen?.(false);
  closeContext({ restoreFocus: false });
  panelKind = kind;
  const generation = ++panelGeneration;
  $('aide-context-title').textContent = { jobs: 'background work', memory: 'memory', conversation: 'conversation' }[kind];
  $('aide-context-content').replaceChildren(node('p', 'loading…', 'aide-context-empty'));
  $('aide-context-overlay').hidden = false;
  $('aide-jobs-open').setAttribute('aria-expanded', String(kind === 'jobs'));
  panelInert = suspend([document.querySelector('.app')]);
  panelBoundary.activate({ focus: $('aide-context-close'), source: kind === 'jobs' ? $('aide-jobs-open') : $('aide-more-btn') });
  if (kind === 'jobs') await refreshJobs({ visible: true });
  if (kind === 'memory') await renderMemory(generation);
}

function initArchiveFocusControls() {
  const archive = $('aide-sidebar');
  if (!archive) return;
  const sync = () => {
    // These legacy actions remain callable by the central menu, but do not
    // belong to the archive's visible controls or its modal keyboard boundary.
    for (const element of archive.querySelectorAll('.sidebar-nav, .aide-sidebar-foot, .session-item .star')) {
      element.hidden = true;
      element.inert = true;
    }
  };
  sync();
  // Session-list refreshes replace the stars along with their conversation rows.
  new MutationObserver(sync).observe(archive, { childList: true, subtree: true });
}

function archiveVisibility(open) {
  restoreInert(archiveInert);
  archiveInert = [];
  if (open) {
    menu?.close({ restoreFocus: false });
    closeContext({ restoreFocus: false });
    window._closeAideTools?.();
    archiveInert = suspend([document.querySelector('.main'), $('aide-work-panel'), $('artifact-panel')]);
    archiveBoundary.activate({ focus: $('aide-sidebar-close'), source: $('aide-more-btn') });
  } else archiveBoundary.deactivate({ restoreFocus: false });
}

export function initAideCentral() {
  if (initialized || !$('aide-mode-conversation')) return;
  initialized = true;
  document.body.classList.add('aide-central');
  document.body.dataset.aideMode = 'conversation';
  initAideCodingWorkspace();
  const options = $('aide-new-context');
  for (const id of ['effort-btn', 'aide-help']) if ($(id)) options.append($(id));
  const closeOptions = action('close conversation settings', () => {
    options.classList.remove('aide-context-requested');
    $('aide-more-btn').focus();
  });
  closeOptions.id = 'aide-options-close';
  closeOptions.setAttribute('aria-label', 'close conversation settings');
  closeOptions.dataset.kokuenIcon = 'close';
  options.append(closeOptions);
  menu = createMenuController($('aide-more-menu'), { onClose: () => $('aide-more-btn').setAttribute('aria-expanded', 'false') });
  panelBoundary = createFocusBoundary($('aide-context-panel'), { onEscape: () => closeContext() });
  initArchiveFocusControls();
  archiveBoundary = createFocusBoundary($('aide-sidebar'), { onEscape: () => {
    window._setAideArchiveOpen?.(false);
    $('aide-more-btn').focus();
  } });
  window._aideArchiveVisibility = archiveVisibility;
  window._showPrimaryAide = openPrimaryConversation;
  window._aideConversationShown = () => {
    if (!openingCall) void setMode('conversation').then(showPrimaryFailure);
    window._setAideArchiveOpen?.(false);
    syncHistory();
  };
  window._hideAideSurfaces = () => {
    closeContext({ restoreFocus: false });
    closeAideCodingWorkspace();
    window._hideLiveVoiceSurface?.();
    $('aide-call-workspace').hidden = true;
    $('aide-call-open').setAttribute('aria-expanded', 'false');
    window._setAideArchiveOpen?.(false);
    menu?.close({ restoreFocus: false });
  };
  $('aide-mode-conversation').addEventListener('click', () => {
    window._enterChatView?.();
    void setMode('conversation', { focus: true });
  });
  $('aide-mode-coding').addEventListener('click', () => {
    window._enterChatView?.();
    void setMode('coding');
  });
  $('aide-return-primary').addEventListener('click', openPrimaryConversation);
  $('aide-history-return').addEventListener('click', openPrimaryConversation);
  $('aide-jobs-open').addEventListener('click', () => openContext('jobs'));
  $('aide-context-close').addEventListener('click', () => closeContext());
  $('aide-context-overlay').addEventListener('click', event => {
    if (event.target === event.currentTarget) closeContext();
  });
  $('aide-more-btn').addEventListener('click', () => {
    if (!$('aide-more-menu').hidden) menu.close();
    else { menu.open({ source: $('aide-more-btn') }); $('aide-more-btn').setAttribute('aria-expanded', 'true'); }
  });
  $('aide-more-menu').addEventListener('click', event => {
    const value = event.target.closest('[data-aide-central-action]')?.dataset.aideCentralAction;
    if (!value) return;
    menu.close();
    if (value === 'archive') window._setAideArchiveOpen?.(true);
    else if (value === 'memory') void openContext('memory');
    else if (value === 'options') {
      window._enterChatView?.();
      options.classList.add('aide-context-requested');
      $('aide-project-context')?.focus();
    }
    else if (value === 'scheduled') $('aide-scheduled-link')?.click();
    else if (value === 'skills') window._navigateTo?.('skills');
    else if (value === 'tools') $('aide-work-panel-toggle')?.click();
    else if (value === 'private') $('incognito-btn')?.click();
    else if (value === 'share') window._openAideSessionActions?.($('aide-more-btn'));
    else if (value === 'settings') window._openSettings?.();
  });
  window.addEventListener('aide:call-surface', event => {
    if (event.detail?.open) {
      if (!callReturnCaptured) callReturnMode = document.body.dataset.aideMode === 'coding' ? 'coding' : 'conversation';
      callReturnCaptured = true;
      openingCall = true;
      window._enterChatView?.();
      openingCall = false;
      void setMode('call');
    } else {
      callReturnCaptured = false;
      if (document.body.dataset.aideMode === 'call') void setMode(callReturnMode, { focus: true, restore: true });
    }
  });
  document.addEventListener('aide-coding-close', () => void setMode('conversation', { focus: true }));
  document.addEventListener('alles:aide-coding-open', () => void setMode('coding'));
  document.addEventListener('alles:aide-session', syncHistory);
  document.addEventListener('alles:aide-primary-unavailable', showPrimaryFailure);
  document.addEventListener('alles:aide-work-changed', () => void refreshJobs({ visible: true }));
  function observeSpace() {
    clearTimeout(refreshTimer);
    if (document.body.dataset.space !== 'aide') {
      closeContext({ restoreFocus: false });
      window._setAideArchiveOpen?.(false);
      menu.close({ restoreFocus: false });
      return;
    }
    syncHistory();
    void refreshJobs();
  }
  new MutationObserver(observeSpace).observe(document.body, { attributes: true, attributeFilter: ['data-space'] });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) observeSpace(); });
  observeSpace();
}

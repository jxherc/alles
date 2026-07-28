import { urlForApp } from './subdomain.js?v=237';
import { getProjects, loadProjects } from './projects.js';
import { createSession, getActiveId, markActive } from './sessions.js';
import { getCurrentEndpoint, getSelected } from './models.js?v=212';
import { prompt as dlgPrompt } from './dialog.js';
import { toast } from './util.js';
import { t } from './i18n.js';

const $ = id => document.getElementById(id);

let panelReturnFocus = null;
let railFrame = 0;
let branchContext = null;
let branchContextRequest = 0;
let terminal = null;
let terminalFit = null;
let terminalSocket = null;
let terminalResizeObserver = null;
let terminalLoad = null;
let terminalTaskContext = '';

function isAide() {
  return document.body.dataset.space === 'aide';
}

function selectedProject(session = window._currentSession) {
  const id = session?.project_id || window._pendingProjectId || '';
  return getProjects().find(project => project.id === id) || null;
}

function selectedWorkingDir(session = window._currentSession) {
  if (session?.environment?.kind === 'legacy_folder') return session.environment.cwd || '';
  return window._pendingWorkingDir || '';
}

function taskContextIdentity(session = window._currentSession) {
  const hasSession = !!session?.id;
  const projectId = hasSession ? (session.project_id || '') : (window._pendingProjectId || '');
  const workingDir = hasSession
    ? (session.environment?.kind === 'legacy_folder' ? (session.environment.cwd || '') : '')
    : (window._pendingWorkingDir || '');
  return [session?.id || '', projectId, workingDir].join('\u0000');
}

function capturePendingTaskContext() {
  return {
    projectId: window._pendingProjectId || '',
    workingDir: window._pendingWorkingDir || '',
  };
}

function restorePendingTaskContext(context) {
  window._pendingProjectId = context.projectId;
  window._pendingWorkingDir = context.workingDir;
  syncNewTaskContext(window._currentSession || null);
}

function folderName(path = '') {
  return String(path).split('/').filter(Boolean).at(-1) || 'folder';
}

function closeProjectMenu({ restoreFocus = false } = {}) {
  const button = $('aide-project-context');
  const menu = $('aide-project-context-menu');
  if (!button || !menu) return;
  menu.hidden = true;
  menu.classList.remove('folder-mode');
  menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', t('aide.choose_project'));
  button.setAttribute('aria-expanded', 'false');
  if (restoreFocus) button.focus();
}

function closeBranchMenu({ restoreFocus = false } = {}) {
  const button = $('aide-branch-context');
  const menu = $('aide-branch-context-menu');
  if (!button || !menu) return;
  menu.hidden = true;
  menu.style.removeProperty('left');
  button.setAttribute('aria-expanded', 'false');
  if (restoreFocus) button.focus();
}

async function patchSessionContext(values) {
  const sessionId = getActiveId();
  if (!sessionId) return null;
  const response = await fetch(`/api/sessions/${sessionId}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(values),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || 'task context could not be changed');
  window._currentSession = data;
  return data;
}

async function chooseProject(id = '') {
  const previousContext = capturePendingTaskContext();
  window._pendingProjectId = id;
  window._pendingWorkingDir = '';
  syncNewTaskContext();
  closeProjectMenu({ restoreFocus: true });
  try {
    const updated = await patchSessionContext({ project_id: id, working_dir: '' });
    if (updated) syncNewTaskContext(updated);
  } catch (error) {
    restorePendingTaskContext(previousContext);
    toast(error.message, 'error');
  }
}

function renderProjectMenu() {
  const menu = $('aide-project-context-menu');
  if (!menu) return;
  const current = window._currentSession?.project_id || window._pendingProjectId || '';
  const choices = [{ id: '', name: t('tasks.title') }, ...getProjects()];
  menu.classList.remove('folder-mode');
  menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', t('aide.choose_project'));
  const projectButtons = choices.map(project => {
    const item = document.createElement('button');
    item.type = 'button';
    item.role = 'menuitemradio';
    item.dataset.projectId = project.id;
    item.setAttribute('aria-checked', String(project.id === current));
    item.textContent = project.name;
    item.addEventListener('click', () => chooseProject(project.id));
    return item;
  });
  const divider = document.createElement('div');
  divider.className = 'aide-project-context-divider';
  const addFolder = document.createElement('button');
  addFolder.type = 'button';
  addFolder.role = 'menuitem';
  addFolder.className = 'aide-project-add-folder';
  addFolder.textContent = 'choose folder…';
  addFolder.addEventListener('click', event => {
    event.stopPropagation();
    openFolderBrowser();
  });
  menu.replaceChildren(...projectButtons, divider, addFolder);
}

function openProjectMenu() {
  const button = $('aide-project-context');
  const menu = $('aide-project-context-menu');
  if (!button || !menu) return;
  closeBranchMenu();
  renderProjectMenu();
  menu.hidden = false;
  button.setAttribute('aria-expanded', 'true');
  menu.querySelector('[aria-checked="true"]')?.focus();
}

async function fetchWithRecentOwner(input, init, reason = 'choose a Project folder') {
  let response = await fetch(input, init);
  if (response.status !== 403) return response;
  const me = await fetch('/api/auth/me').then(result => result.json()).catch(() => null);
  if (me?.enabled === false) return response;
  const password = await dlgPrompt(`enter your Alles password to ${reason}`, '', { secret: true });
  if (password == null) return response;
  const confirmed = await fetch('/api/auth/reauth', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  if (!confirmed.ok) {
    toast('password confirmation failed', 'error');
    return response;
  }
  return fetch(input, init);
}

function syncBranchButton() {
  const button = $('aide-branch-context');
  const label = $('aide-branch-context-label');
  if (!button || !label) return;
  const available = !!branchContext?.repository && !!branchContext.current;
  button.hidden = !available;
  label.textContent = available ? branchContext.current : 'branch';
  button.title = available
    ? `${branchContext.current}${branchContext.dirty ? ' · uncommitted changes' : ''}`
    : '';
}

function branchEndpoint(project, session = window._currentSession) {
  if (session?.id) return `/api/sessions/${session.id}/git/branches`;
  if (project?.id) return `/api/projects/${project.id}/git/branches`;
  return '';
}

async function loadBranchContext(project, session = window._currentSession) {
  const request = ++branchContextRequest;
  branchContext = null;
  closeBranchMenu();
  syncBranchButton();
  const endpoint = branchEndpoint(project, session);
  if (!endpoint) return;
  try {
    const response = await fetch(endpoint);
    const data = response.ok ? await response.json() : null;
    if (request !== branchContextRequest) return;
    branchContext = data?.repository ? data : null;
  } catch {
    if (request !== branchContextRequest) return;
    branchContext = null;
  }
  syncBranchButton();
}

function renderBranchMenu() {
  const menu = $('aide-branch-context-menu');
  if (!menu || !branchContext?.repository) return;
  const buttons = branchContext.branches.map(branch => {
    const item = document.createElement('button');
    item.type = 'button';
    item.role = 'menuitemradio';
    item.dataset.branch = branch;
    item.setAttribute('aria-checked', String(branch === branchContext.current));
    item.textContent = branch;
    item.addEventListener('click', () => chooseBranch(branch));
    return item;
  });
  menu.replaceChildren(...buttons);
}

function openBranchMenu() {
  const button = $('aide-branch-context');
  const menu = $('aide-branch-context-menu');
  if (!button || !menu || !branchContext?.repository) return;
  closeProjectMenu();
  renderBranchMenu();
  menu.hidden = false;
  const parent = menu.offsetParent;
  if (parent) {
    const parentBox = parent.getBoundingClientRect();
    const buttonBox = button.getBoundingClientRect();
    const inset = 3;
    const maximum = Math.max(inset, parentBox.width - menu.offsetWidth - inset);
    const desired = buttonBox.left - parentBox.left;
    menu.style.left = `${Math.round(Math.min(Math.max(desired, inset), maximum))}px`;
  }
  button.setAttribute('aria-expanded', 'true');
  menu.querySelector('[aria-checked="true"]')?.focus();
}

async function chooseBranch(branch) {
  const project = selectedProject();
  const endpoint = branchEndpoint(project);
  const menu = $('aide-branch-context-menu');
  if (!endpoint || !menu || !branch || branch === branchContext?.current) {
    closeBranchMenu({ restoreFocus: true });
    return;
  }
  menu.setAttribute('aria-busy', 'true');
  try {
    const response = await fetchWithRecentOwner(
      endpoint,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ branch }),
      },
      'switch this working branch',
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      closeBranchMenu({ restoreFocus: true });
      const message = ['project_git_switch_failed', 'session_git_switch_failed'].includes(data.code)
        ? 'this branch would overwrite your changes. commit or stash them first.'
        : (data.detail || 'Git could not switch branches');
      toast(message, 'error');
      return;
    }
    branchContext = data;
    syncBranchButton();
    closeBranchMenu({ restoreFocus: true });
  } catch {
    toast('Git branch state is unavailable', 'error');
  } finally {
    menu.removeAttribute('aria-busy');
  }
}

function folderButton(folder, onOpen) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'aide-folder-row';
  button.dataset.folderPath = folder.path;
  button.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 6.5h6l2-2h9v14h-17z"/></svg>';
  const name = document.createElement('span');
  name.textContent = folder.name;
  button.append(name);
  button.addEventListener('click', () => onOpen(folder.path));
  return button;
}

async function createProjectFromFolder(path) {
  const response = await fetchWithRecentOwner('/api/projects', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ working_dir: path }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    toast(data.detail || 'Project folder could not be added', 'error');
    return;
  }
  await loadProjects();
  const previousContext = capturePendingTaskContext();
  window._pendingProjectId = data.id;
  window._pendingWorkingDir = '';
  try {
    await patchSessionContext({ project_id: data.id, working_dir: '' });
  } catch (error) {
    restorePendingTaskContext(previousContext);
    toast(error.message, 'error');
    return;
  }
  await window._reloadAideSessions?.();
  syncNewTaskContext();
  closeProjectMenu({ restoreFocus: true });
  toast(`Project “${data.name}” added`, 'success');
}

async function useTemporaryFolder(path) {
  const previousContext = capturePendingTaskContext();
  window._pendingProjectId = '';
  window._pendingWorkingDir = path;
  try {
    const updated = await patchSessionContext({ project_id: '', working_dir: path });
    syncNewTaskContext(updated || null);
    closeProjectMenu({ restoreFocus: true });
  } catch (error) {
    restorePendingTaskContext(previousContext);
    toast(error.message, 'error');
  }
}

async function openFolderBrowser(path = '') {
  const menu = $('aide-project-context-menu');
  if (!menu) return;
  menu.classList.add('folder-mode');
  menu.setAttribute('role', 'dialog');
  menu.setAttribute('aria-label', 'choose a project folder');
  menu.setAttribute('aria-busy', 'true');
  menu.replaceChildren(Object.assign(document.createElement('div'), {
    className: 'aide-folder-loading',
    textContent: 'opening folders…',
  }));
  const query = path ? `?path=${encodeURIComponent(path)}` : '';
  let response;
  let data;
  try {
    response = await fetchWithRecentOwner(`/api/project-folders${query}`);
    data = await response.json().catch(() => ({}));
  } catch {
    response = { ok: false };
    data = { detail: 'Alles could not reach the local server.' };
  }
  menu.setAttribute('aria-busy', 'false');
  if (!response.ok) {
    menu.replaceChildren();
    const message = document.createElement('div');
    message.className = 'aide-folder-error';
    message.textContent = data.detail || 'That folder could not be opened.';
    const back = document.createElement('button');
    back.type = 'button';
    back.textContent = 'back';
    back.addEventListener('click', renderProjectMenu);
    menu.append(message, back);
    return;
  }

  const header = document.createElement('div');
  header.className = 'aide-folder-head';
  const back = document.createElement('button');
  back.type = 'button';
  back.textContent = '‹';
  back.setAttribute('aria-label', 'back to projects');
  back.addEventListener('click', renderProjectMenu);
  const title = document.createElement('span');
  title.textContent = 'project folder';
  header.append(back, title);

  const pathForm = document.createElement('form');
  pathForm.className = 'aide-folder-path';
  const pathInput = document.createElement('input');
  pathInput.type = 'text';
  pathInput.value = data.path;
  pathInput.setAttribute('aria-label', 'server folder path');
  pathInput.autocomplete = 'off';
  const go = document.createElement('button');
  go.type = 'submit';
  go.textContent = 'go';
  pathForm.append(pathInput, go);
  pathForm.addEventListener('submit', event => {
    event.preventDefault();
    openFolderBrowser(pathInput.value.trim());
  });

  const list = document.createElement('div');
  list.className = 'aide-folder-list';
  if (data.parent) {
    list.append(folderButton({ name: '..', path: data.parent }, openFolderBrowser));
  }
  (data.folders || []).forEach(folder => list.append(folderButton(folder, openFolderBrowser)));
  if (!data.parent && !(data.folders || []).length) {
    list.append(Object.assign(document.createElement('div'), {
      className: 'aide-folder-empty',
      textContent: 'no folders here',
    }));
  }

  const footer = document.createElement('div');
  footer.className = 'aide-folder-actions';
  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.textContent = 'cancel';
  cancel.addEventListener('click', () => closeProjectMenu({ restoreFocus: true }));
  const use = document.createElement('button');
  use.type = 'button';
  use.className = 'aide-folder-use';
  use.textContent = 'use for this task';
  use.addEventListener('click', () => useTemporaryFolder(data.path));
  const save = document.createElement('button');
  save.type = 'button';
  save.textContent = 'save as project';
  save.addEventListener('click', () => createProjectFromFolder(data.path));
  footer.append(cancel, save, use);
  menu.replaceChildren(header, pathForm, list, footer);
  pathInput.focus();
  pathInput.setSelectionRange(pathInput.value.length, pathInput.value.length);
}

function syncNewTaskContext(session = window._currentSession) {
  const row = $('aide-new-context');
  const label = $('aide-project-context-label');
  if (!row || !label) return;
  const nextTerminalTaskContext = taskContextIdentity(session);
  if (terminalTaskContext && terminalTaskContext !== nextTerminalTaskContext) {
    setTerminalOpen(false);
  }
  terminalTaskContext = nextTerminalTaskContext;
  row.hidden = !isAide();
  if (session) {
    window._pendingProjectId = session.project_id || '';
    window._pendingWorkingDir = session.environment?.kind === 'legacy_folder'
      ? (session.environment.cwd || '')
      : '';
  }
  const project = selectedProject(session);
  const workingDir = selectedWorkingDir(session);
  label.textContent = project?.name || (workingDir ? folderName(workingDir) : t('tasks.title'));
  closeProjectMenu();
  if (!row.hidden) loadBranchContext(project, session);
  else {
    branchContextRequest += 1;
    branchContext = null;
    syncBranchButton();
  }
}

function setPanelOpen(open, focusInside = true) {
  const panel = $('aide-work-panel');
  const toggle = $('aide-work-panel-toggle');
  if (!panel || !toggle) return;
  if (!open) setTerminalOpen(false);
  panelReturnFocus = open ? document.activeElement : panelReturnFocus;
  panel.hidden = !open;
  panel.inert = !open;
  panel.setAttribute('aria-hidden', String(!open));
  toggle.setAttribute('aria-expanded', String(open));
  toggle.setAttribute('aria-label', open ? 'close task tools' : 'open task tools');
  document.body.classList.toggle('aide-work-panel-open', open);
  if (open && focusInside) requestAnimationFrame(() => panel.querySelector('button:not([hidden])')?.focus());
  if (!open && focusInside && panelReturnFocus instanceof HTMLElement) panelReturnFocus.focus();
}

function terminalTheme() {
  const style = getComputedStyle(document.body);
  const value = name => style.getPropertyValue(name).trim();
  return {
    background: value('--bg') || '#0a0a0a',
    foreground: value('--text') || '#ededed',
    cursor: value('--text') || '#ededed',
    cursorAccent: value('--bg') || '#0a0a0a',
    selectionBackground: value('--accent') || '#7c83ff',
    black: value('--bg') || '#0a0a0a',
    brightBlack: value('--muted') || '#777777',
  };
}

async function terminalSocketUrl() {
  await ensureTerminalTaskContext();
  const url = new URL('/api/shell/pty', window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  const sessionId = getActiveId() || '';
  const projectId = sessionId ? '' : (window._pendingProjectId || '');
  if (sessionId) url.searchParams.set('session_id', sessionId);
  if (projectId) url.searchParams.set('project_id', projectId);
  return url;
}

async function ensureTerminalTaskContext() {
  if (getActiveId() || window._pendingProjectId || !window._pendingWorkingDir) return;
  const endpoint = getCurrentEndpoint();
  const selected = getSelected();
  const session = await createSession(
    selected?.model || endpoint?.models?.[0] || '',
    selected?.endpointId || endpoint?.id || '',
    {
      mode: 'agent',
      chatBehavior: window._pendingChatBehavior || '',
      workingDir: window._pendingWorkingDir,
    },
  );
  if (!session) throw new Error('task folder could not be saved for the terminal');
  window._currentSession = session;
  // Materializing the pending folder as a session changes its identifier, not
  // the terminal's effective task context. Keep this internal transition open.
  terminalTaskContext = taskContextIdentity(session);
  markActive(session.id);
  syncNewTaskContext(session);
}

function sendTerminalResize() {
  if (!terminal || terminalSocket?.readyState !== WebSocket.OPEN) return;
  terminalSocket.send(JSON.stringify({
    type: 'resize',
    cols: terminal.cols,
    rows: terminal.rows,
  }));
}

function fitTerminal() {
  if (!terminal || !terminalFit || $('aide-terminal')?.hidden) return;
  try {
    terminalFit.fit();
    sendTerminalResize();
  } catch (_) {}
}

function disconnectTerminal() {
  const socket = terminalSocket;
  terminalSocket = null;
  if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000, 'panel closed');
}

async function ensureTerminal() {
  if (terminal) return terminal;
  if (terminalLoad) return terminalLoad;
  terminalLoad = Promise.all([
    import('/static/vendor/xterm/xterm.mjs?v=6.0.0'),
    import('/static/vendor/xterm/addon-fit.mjs?v=0.11.0'),
  ]).then(([core, fit]) => {
    const mount = $('aide-terminal-mount');
    if (!mount) throw new Error('terminal mount is unavailable');
    terminal = new core.Terminal({
      allowProposedApi: false,
      convertEol: false,
      cursorBlink: true,
      fontFamily: "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace",
      fontSize: 13,
      lineHeight: 1.22,
      minimumContrastRatio: 4.5,
      scrollback: 5000,
      theme: terminalTheme(),
    });
    terminalFit = new fit.FitAddon();
    terminal.loadAddon(terminalFit);
    terminal.open(mount);
    terminal.onData(data => {
      if (terminalSocket?.readyState === WebSocket.OPEN) {
        terminalSocket.send(JSON.stringify({ type: 'input', data }));
      }
    });
    terminalResizeObserver = new ResizeObserver(() => requestAnimationFrame(fitTerminal));
    terminalResizeObserver.observe(mount);
    return terminal;
  }).catch(error => {
    terminalLoad = null;
    throw error;
  });
  return terminalLoad;
}

async function connectTerminal() {
  try {
    const socketUrl = await terminalSocketUrl();
    const instance = await ensureTerminal();
    if ($('aide-terminal')?.hidden) return;
    instance.options.theme = terminalTheme();
    instance.reset();
    disconnectTerminal();
    const socket = new WebSocket(socketUrl);
    terminalSocket = socket;
    socket.binaryType = 'arraybuffer';
    socket.addEventListener('message', event => {
      if (socket !== terminalSocket) return;
      if (typeof event.data !== 'string') {
        instance.write(new Uint8Array(event.data));
        return;
      }
      let data = null;
      try { data = JSON.parse(event.data); } catch (_) {}
      if (data?.type === 'ready') {
        requestAnimationFrame(() => {
          fitTerminal();
          instance.focus();
        });
      }
    });
    socket.addEventListener('close', event => {
      if (socket !== terminalSocket) return;
      terminalSocket = null;
      if (event.code !== 1000) {
        instance.writeln(`\r\n\x1b[31m${event.reason || 'terminal disconnected'}\x1b[0m`);
      }
    });
    socket.addEventListener('error', () => {
      if (socket === terminalSocket) instance.writeln('\r\n\x1b[31mterminal unavailable\x1b[0m');
    });
  } catch (error) {
    toast(String(error.message || error), 'error');
  }
}

function setTerminalOpen(open) {
  const terminal = $('aide-terminal');
  const tools = $('aide-task-tools');
  const panel = $('aide-work-panel');
  const back = $('aide-work-panel-back');
  const title = $('aide-work-panel-title');
  if (!terminal || !tools || !panel || !back || !title) return;
  terminal.hidden = !open;
  tools.hidden = open;
  panel.classList.toggle('terminal-open', open);
  back.hidden = !open;
  title.textContent = open ? 'terminal' : 'task tools';
  if (open) {
    connectTerminal();
  } else disconnectTerminal();
}

function openDestination(tool) {
  if (tool === 'terminal') {
    setTerminalOpen(true);
    return;
  }
  setPanelOpen(false, false);
  if (tool === 'files') {
    document.querySelector('[data-view="files"]')?.click();
  } else if (tool === 'browser') {
    window.location.assign(urlForApp('andromeda'));
  } else if (tool === 'side-task') {
    $('new-chat-btn')?.click();
    $('composer-ta')?.focus();
  } else if (tool === 'review') {
    document.querySelector('[data-view="activity"]')?.click();
  }
}

function userRows() {
  return [...document.querySelectorAll('#messages .msg-row')].filter(row => row.querySelector('.user-bubble'));
}

function setRailPosition() {
  railFrame = 0;
  const rail = $('aide-message-rail');
  const track = $('aide-message-rail-track');
  const chat = $('chat');
  if (!rail || !track || !chat || rail.hidden) return;
  const rows = userRows();
  const viewport = chat.getBoundingClientRect();
  const focusY = viewport.top + viewport.height * 0.5;
  let closest = 0;
  let distance = Infinity;
  const atTop = chat.scrollTop <= 3;
  const atBottom = chat.scrollTop + chat.clientHeight >= chat.scrollHeight - 3;
  if (atTop && !atBottom) closest = 0;
  else if (atBottom && !atTop) closest = Math.max(0, rows.length - 1);
  else rows.forEach((row, index) => {
    const rect = row.getBoundingClientRect();
    const nextDistance = Math.abs(rect.top + rect.height / 2 - focusY);
    if (nextDistance < distance) {
      closest = index;
      distance = nextDistance;
    }
  });
  track.querySelectorAll('button').forEach((tick, index) => {
    tick.classList.toggle('current', index === closest);
    tick.setAttribute('aria-current', index === closest ? 'true' : 'false');
  });
}

function queueRailPosition() {
  if (!railFrame) railFrame = requestAnimationFrame(setRailPosition);
}

function rebuildRail() {
  const rail = $('aide-message-rail');
  const track = $('aide-message-rail-track');
  if (!rail || !track) return;
  const rows = userRows();
  rail.hidden = !isAide() || rows.length < 3;
  rail.setAttribute('aria-label', `${rows.length} messages from you`);
  if (rail.hidden) {
    track.replaceChildren();
    return;
  }
  const ticks = [...track.children];
  const keys = rows.map(row => {
    if (!row._aideRailKey) row._aideRailKey = row.dataset.msgId || crypto.randomUUID();
    return row._aideRailKey;
  });
  const stable = ticks.length === rows.length
    && ticks.every((tick, index) => tick.dataset.messageKey === keys[index]);
  if (!stable) {
    const existing = new Map(ticks.map(tick => [tick.dataset.messageKey, tick]));
    const next = rows.map((row, index) => {
      const key = keys[index];
      const tick = existing.get(key) || document.createElement('button');
      tick.type = 'button';
      tick._aideMessageRow = row;
      tick.dataset.messageKey = key;
      tick.setAttribute('aria-label', `jump to message ${index + 1}`);
      if (!tick.dataset.wired) {
        tick.dataset.wired = '1';
        tick.addEventListener('click', () => tick._aideMessageRow?.scrollIntoView({
          block: 'center',
          behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
        }));
      }
      return tick;
    });
    track.replaceChildren(...next);
  }
  if (railFrame) cancelAnimationFrame(railFrame);
  setRailPosition();
}

export function initAideWorkspace() {
  const panel = $('aide-work-panel');
  const toggle = $('aide-work-panel-toggle');
  const messages = $('messages');
  const chat = $('chat');
  if (!panel || !toggle || !messages || !chat || panel.dataset.wired) return;
  panel.dataset.wired = '1';
  window._syncAideNewTaskContext = syncNewTaskContext;
  $('aide-project-context')?.addEventListener('click', event => {
    event.stopPropagation();
    const menu = $('aide-project-context-menu');
    if (menu?.hidden) openProjectMenu();
    else closeProjectMenu({ restoreFocus: true });
  });
  $('aide-project-context-menu')?.addEventListener('keydown', event => {
    const items = [...event.currentTarget.querySelectorAll('[role="menuitemradio"]')];
    const index = items.indexOf(document.activeElement);
    if (event.key === 'Escape') {
      event.preventDefault();
      closeProjectMenu({ restoreFocus: true });
    } else if (items.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      items[(index + step + items.length) % items.length]?.focus();
    } else if (items.length && (event.key === 'Home' || event.key === 'End')) {
      event.preventDefault();
      items[event.key === 'Home' ? 0 : items.length - 1]?.focus();
    }
  });
  $('aide-branch-context')?.addEventListener('click', event => {
    event.stopPropagation();
    const menu = $('aide-branch-context-menu');
    if (menu?.hidden) openBranchMenu();
    else closeBranchMenu({ restoreFocus: true });
  });
  $('aide-branch-context-menu')?.addEventListener('keydown', event => {
    const items = [...event.currentTarget.querySelectorAll('[role="menuitemradio"]')];
    const index = items.indexOf(document.activeElement);
    if (event.key === 'Escape') {
      event.preventDefault();
      closeBranchMenu({ restoreFocus: true });
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
    if (!event.composedPath().includes($('aide-new-context'))) {
      closeProjectMenu();
      closeBranchMenu();
    }
  });
  toggle.addEventListener('click', () => setPanelOpen(panel.hidden));
  $('aide-work-panel-close')?.addEventListener('click', () => setPanelOpen(false));
  $('aide-work-panel-back')?.addEventListener('click', () => setTerminalOpen(false));
  $('aide-task-tools')?.addEventListener('click', event => {
    const button = event.target.closest('[data-aide-tool]');
    if (button) openDestination(button.dataset.aideTool);
  });
  chat.addEventListener('scroll', queueRailPosition, { passive: true });
  new MutationObserver(rebuildRail).observe(messages, { childList: true, subtree: true });
  new MutationObserver(() => {
    if (!isAide()) setPanelOpen(false, false);
    rebuildRail();
  }).observe(document.body, { attributes: true, attributeFilter: ['data-space'] });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || panel.hidden) return;
    event.preventDefault();
    if (!$('aide-terminal')?.hidden) setTerminalOpen(false);
    else setPanelOpen(false);
  });
  rebuildRail();
  syncNewTaskContext();
}

window.addEventListener('alles:localization-change', () => syncNewTaskContext());

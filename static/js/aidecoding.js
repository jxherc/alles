import { prompt as dlgPrompt } from './dialog.js';
import { toast } from './util.js';
import { wireAutosizeTextarea, autosizeTextarea } from './text_entry.js';
import { formatDateTime } from './i18n.js';
import { requestId } from './request_id.js';

const $ = id => document.getElementById(id);
const icons = {
  back: '<path d="m14 6-6 6 6 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  chevron: '<path d="m8 10 4 4 4-4"/>',
  connection: '<path d="m9 15 6-6M8 12l-2 2a3.5 3.5 0 0 0 5 5l2-2M11 7l2-2a3.5 3.5 0 0 1 5 5l-2 2"/>',
  send: '<path d="M12 19V5m-6 6 6-6 6 6"/>',
};
const icon = name => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (icons[name] || '') + '</svg>';
let host = null, opening = null, selectedWorkspace = null, selectedRunId = null;
let workspaces = [], runs = [], currentView = 'draft', previousView = 'draft', connection = null, selectionVersion = 0;
let submitting = false, pendingStart = null;
let liveSource = null, liveRunId = '', liveRefreshTimer = null, liveReady = false;
const pendingInteractions = new Map(), responseDrafts = new Map();
const followupRequests = new Map(), followupDrafts = new Map();
let followingUp = false;
const eventCache = new Map(), remoteEventCache = new Map();
const stateCopy = {
  starting: ['contacting DSH', 'The session outcome is not verified yet.'],
  awaiting_prompt: ['ready to send', 'The session exists. The saved request has not been accepted.'],
  running: ['request accepted', 'Refresh to check the current DSH state.'],
  cancel_requested: ['stop requested', 'Refresh to confirm whether DSH stopped the turn.'],
  uncertain: ['outcome uncertain', 'Inspect the session in DSH before retrying.'],
  interrupted: ['tracking interrupted', 'DSH may still be working. Refresh before retrying.'],
  succeeded: ['completed', 'DSH confirmed the turn completed.'],
  failed: ['failed', 'DSH ended or rejected this run.'],
  cancelled: ['stopped', 'DSH confirmed the turn stopped.'],
};

async function ownerFetch(input, init = {}, reason = 'manage the DSH coding connection') {
  const response = await fetch(input, init);
  if (response.status !== 403) return response;
  const error = await response.clone().json().catch(() => ({}));
  if (error.code !== 'recent_auth_required') return response;
  const me = await fetch('/api/auth/me').then(result => result.json()).catch(() => null);
  if (me?.enabled === false) return response;
  const password = await dlgPrompt(`enter your Alles password to ${reason}`, '', { secret: true });
  if (password == null) return response;
  const confirmed = await fetch('/api/auth/reauth', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ password }),
  });
  if (!confirmed.ok) { toast('password confirmation failed', 'error'); return response; }
  return fetch(input, init);
}
async function api(path, init = {}, reason) {
  const response = await ownerFetch(path, init, reason);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) { const error = new Error(data.detail || 'DSH request failed'); error.code = data.code || ''; throw error; }
  return data;
}
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}
function formatTime(value, full = false) {
  if (!value || Number.isNaN(new Date(value).getTime())) return '';
  return formatDateTime(value, full ? { dateStyle: 'medium', timeStyle: 'short' }
    : { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}
function setStatus(text, tone = '') {
  if (!$('aide-coding-status')) return;
  $('aide-coding-status').textContent = text;
  $('aide-coding-status').dataset.tone = tone;
}
function setError(text = '') {
  $('aide-coding-error').textContent = text;
  $('aide-coding-error').hidden = !text;
}
function setConnectionState(status) {
  connection = status;
  const configured = status?.configured === true;
  // pairing needs the app; without it, show how to install it instead
  const missing = !configured && status?.installed === false;
  $('aide-coding-install').hidden = !missing;
  $('aide-coding-pair').hidden = configured || missing;
  $('aide-coding-ready').hidden = !configured;
  $('aide-coding-connection-label').textContent = configured ? 'DSH' : 'connect DSH';
  $('aide-coding-connection-toggle').dataset.connected = String(configured);
  $('aide-coding-connect-inline').hidden = configured;
  $('aide-coding-submit').disabled = submitting || !configured || !selectedWorkspace;
  $('aide-coding-prompt').disabled = !configured;
  $('aide-coding-project').disabled = !configured;
  $('aide-coding-draft-status').textContent = configured ? (workspaces.length ? '' : 'No DSH workspaces available.') : 'Connect DSH to work in a local project.';
  if (!configured) { setStatus(status?.installed ? 'DSH is installed · not connected' : 'DSH is not installed'); return; }
  const version = status.host?.version || status.host_version || '';
  setStatus(status.available === true ? `DSH connected${version ? ` · ${version}` : ''}` : 'DSH connected · availability not checked', status.available === true ? 'ok' : '');
  $('aide-coding-connection-address').textContent = status.base_url || '';
}
function closeWorkspaceMenu({ focus = false } = {}) {
  if (!$('aide-coding-workspace-menu')) return;
  $('aide-coding-workspace-menu').hidden = true;
  $('aide-coding-project').setAttribute('aria-expanded', 'false');
  if (focus) $('aide-coding-project').focus();
}
function updateWorkspace() {
  $('aide-coding-project-title').textContent = selectedWorkspace?.title || 'choose workspace';
  $('aide-coding-project-path').textContent = selectedWorkspace?.path || '';
  $('aide-coding-submit').disabled = submitting || !connection?.configured || !selectedWorkspace;
  const buttons = workspaces.map(workspace => {
    const button = element('button'); button.type = 'button'; button.setAttribute('role', 'option');
    button.setAttribute('aria-selected', String(workspace.workspace_id === selectedWorkspace?.workspace_id));
    button.append(element('span', '', workspace.title || 'workspace'), element('small', '', workspace.path || ''));
    button.addEventListener('click', () => { selectedWorkspace = workspace; updateWorkspace(); closeWorkspaceMenu({ focus: true }); });
    return button;
  });
  $('aide-coding-workspace-menu').replaceChildren(...(buttons.length ? buttons : [element('p', 'acw-muted', 'No DSH workspaces available.')]));
}
async function loadWorkspaces() {
  const data = await api('/api/aide/coding/workspaces', {}, 'read DSH workspaces');
  workspaces = data.items || [];
  if (!workspaces.some(item => item.workspace_id === selectedWorkspace?.workspace_id)) selectedWorkspace = workspaces[0] || null;
  updateWorkspace();
  $('aide-coding-draft-status').textContent = workspaces.length ? '' : 'No DSH workspaces available.';
}
function setView(view, { focus = false } = {}) {
  if (currentView !== view) selectionVersion++;
  currentView = view;
  if (view !== 'run') closeLive();
  for (const panel of host.querySelectorAll('[data-coding-view]')) panel.hidden = panel.dataset.codingView !== view;
  host.dataset.pane = view === 'runs' ? 'runs' : 'detail';
  $('aide-coding-connection-toggle').setAttribute('aria-expanded', String(view === 'connection'));
  closeWorkspaceMenu(); setError();
  if (view === 'draft') autosizeTextarea($('aide-coding-prompt'));
  if (focus) (view === 'draft' ? $('aide-coding-prompt') : view === 'connection' ? $('aide-coding-connection-back') : view === 'runs' ? $('aide-coding-new') : $('aide-coding-detail-title'))?.focus();
}
function showConnection() {
  if (currentView === 'connection') { setView(previousView); $('aide-coding-connection-toggle').focus(); return; }
  previousView = currentView; setView('connection', { focus: true });
}
function renderRuns() {
  const list = $('aide-coding-run-list');
  const focusedId = list.contains(document.activeElement) ? document.activeElement?.dataset.runId : null;
  $('aide-coding-run-count').textContent = runs.length ? String(runs.length) : '';
  const rows = runs.map(run => {
    const row = element('button', 'acw-run-option'); row.type = 'button'; row.dataset.runId = run.id; row.dataset.state = run.state;
    row.setAttribute('aria-current', String(selectedRunId === run.id && currentView === 'run'));
    row.append(element('span', 'acw-run-option-title', run.prompt || 'coding run'));
    const meta = element('span', 'acw-run-option-meta'), time = element('time', '', formatTime(run.created_at));
    time.dateTime = run.created_at || '';
    meta.append(element('span', 'acw-run-state', (stateCopy[run.state] || [run.state])[0]), time);
    row.append(meta); row.addEventListener('click', () => selectRun(run.id, { focus: true })); return row;
  });
  list.replaceChildren(...(rows.length ? rows : [element('p', 'acw-rail-empty', 'Your coding runs appear here.')]));
  if (focusedId) [...list.querySelectorAll('[data-run-id]')].find(button => button.dataset.runId === focusedId)?.focus();
}
function runAction(label, action, id) {
  const button = element('button', 'acw-action', label); button.type = 'button'; button.dataset.runAction = action; button.dataset.runId = id; return button;
}
function renderEvents(runId) {
  if (runId !== selectedRunId) return;
  const remote = remoteEventCache.get(runId) || [];
  $('aide-coding-remote').hidden = !remote.length;
  $('aide-coding-remote-events').replaceChildren(...remote.map(event => element('li', '', event.summary || event.type || 'event')));
  const output = remote.filter(event => event.text || event.diffs?.length);
  $('aide-coding-output').hidden = !output.length;
  $('aide-coding-output-body').replaceChildren(...output.map(event => {
    const section = element('section', 'acw-output-entry');
    section.append(element('h4', '', event.type === 'assistant/message' ? 'response' : event.summary));
    if (event.text) section.append(element('pre', 'acw-output-text', event.text));
    for (const diff of event.diffs || []) {
      section.append(element('h4', 'acw-path', diff.path || 'file change'));
      if (diff.patch) section.append(element('pre', 'acw-output-text', diff.patch));
      else {
        if (diff.oldText != null) { section.append(element('p', 'acw-muted', 'before')); section.append(element('pre', 'acw-output-text', diff.oldText)); }
        if (diff.newText != null) { section.append(element('p', 'acw-muted', 'after')); section.append(element('pre', 'acw-output-text', diff.newText)); }
      }
    }
    return section;
  }));
  const cached = eventCache.get(runId), list = $('aide-coding-events');
  if (!cached) { list.replaceChildren(element('li', 'acw-muted', 'loading activity…')); return; }
  if (cached.error) { list.replaceChildren(element('li', 'acw-muted', cached.error)); return; }
  const rows = cached.items.map(event => {
    const item = element('li', 'acw-event'), time = element('time', '', formatTime(event.created_at));
    time.dateTime = event.created_at || '';
    item.append(element('span', '', event.summary || event.kind || 'event'), time);
    if (event.kind === 'followup_requested' && event.data?.prompt) item.append(element('p', '', event.data.prompt));
    return item;
  });
  list.replaceChildren(...(rows.length ? rows : [element('li', 'acw-muted', 'No activity recorded.')]));
}
function renderSelectedRun() {
  const run = runs.find(item => item.id === selectedRunId); if (!run) return;
  if (run.terminal && liveRunId === run.id) { closeLive(); pendingInteractions.clear(); renderPending(); liveStatus(''); }
  $('aide-coding-run-detail').dataset.state = run.state;
  const [state, explanation] = stateCopy[run.state] || [run.state, ''];
  $('aide-coding-detail-state').textContent = state;
  $('aide-coding-detail-title').textContent = run.prompt || 'coding run';
  $('aide-coding-detail-path').textContent = run.workspace_path || run.workspace_id || '';
  $('aide-coding-detail-time').textContent = `updated ${formatTime(run.updated_at, true)}`;
  $('aide-coding-result-title').textContent = run.terminal ? 'result' : 'status';
  $('aide-coding-result-status').textContent = run.safe_error || explanation;
  $('aide-coding-result-note').hidden = false;
  $('aide-coding-followup').hidden = !run.terminal;
  const actions = [runAction('refresh', 'refresh', run.id)];
  if (run.state === 'awaiting_prompt') actions.push(runAction('send saved request', 'resume', run.id));
  if (['starting', 'awaiting_prompt', 'running', 'uncertain', 'interrupted'].includes(run.state)) actions.push(runAction('stop', 'cancel', run.id));
  $('aide-coding-run-actions').replaceChildren(...actions);
  $('aide-coding-record-id').textContent = run.id;
  $('aide-coding-record-session').textContent = run.provider_session_id || 'not assigned';
  renderEvents(run.id);
}
async function loadEvents(runId) {
  try { const data = await api(`/api/aide/coding/runs/${encodeURIComponent(runId)}/events`, {}, 'read coding activity'); eventCache.set(runId, { items: data.items || [] }); if (Array.isArray(data.remote_events)) remoteEventCache.set(runId, data.remote_events); }
  catch (error) { eventCache.set(runId, { error: `Activity unavailable. ${error.message}` }); }
  renderEvents(runId);
}
async function selectRun(id, { focus = false } = {}) {
  if (selectedRunId) followupDrafts.set(selectedRunId, $('aide-coding-followup-prompt').value);
  selectedRunId = id; selectionVersion++; setView('run'); renderRuns(); renderSelectedRun();
  $('aide-coding-followup-prompt').value = followupDrafts.get(id) || '';
  autosizeTextarea($('aide-coding-followup-prompt'));
  if (focus) $('aide-coding-detail-title').focus();
  await loadEvents(id);
  if (selectedRunId === id && !host.hidden) connectLive(id);
}
async function loadRuns({ chooseFirst = false } = {}) {
  const version = selectionVersion, data = await api('/api/aide/coding/runs?limit=100', {}, 'read coding runs');
  runs = data.items || []; renderRuns();
  if (chooseFirst && version === selectionVersion && currentView === 'draft' && !selectedRunId && !$('aide-coding-prompt').value && runs.length) await selectRun(runs[0].id);
  else if (currentView === 'run') renderSelectedRun();
}
async function loadStatus() {
  let statusError = null;
  try {
    const status = await api('/api/aide/coding/status', {}, 'read the DSH coding connection'); setConnectionState(status);
    if (status.configured) {
      try { await loadWorkspaces(); }
      catch (error) { workspaces = []; selectedWorkspace = null; updateWorkspace(); setStatus('DSH connected · unavailable right now', 'warning'); $('aide-coding-draft-status').textContent = 'Workspaces unavailable. Check the DSH connection.'; }
    }
  } catch (error) { statusError = error.message; setStatus(error.message, 'error'); }
  try { await loadRuns({ chooseFirst: true }); }
  catch (error) { setError(`Saved runs unavailable. ${error.message}`); }
  if (statusError) setError(statusError);
  if (currentView === 'run' && selectedRunId && !host.hidden) connectLive(selectedRunId);
}
async function runMutation(runId, action) {
  const data = await api(`/api/aide/coding/runs/${encodeURIComponent(runId)}/${action}`, { method: 'POST' }, `${action} this DSH run`);
  if (Array.isArray(data.remote_events)) remoteEventCache.set(runId, data.remote_events);
  await loadRuns(); await loadEvents(runId);
  if (selectedRunId === runId) renderPending();
}

function closeLive() {
  liveSource?.close(); liveSource = null; liveRunId = ''; liveReady = false;
  clearTimeout(liveRefreshTimer);
}
function liveStatus(text) { $('aide-coding-live-status').textContent = text; }
function scheduleLiveRefresh(runId) {
  if (liveRefreshTimer) return;
  liveRefreshTimer = setTimeout(async () => {
    liveRefreshTimer = null;
    if (liveRunId !== runId) return;
    try { await runMutation(runId, 'refresh'); }
    catch { liveStatus('could not refresh output; saved results remain available'); }
  }, 350);
}
async function respondTo(frame, response, button) {
  if (!liveReady || button.disabled) return;
  const runId = liveRunId;
  for (const control of button.closest('form').querySelectorAll('button, textarea')) control.disabled = true;
  try {
    const receipt = await api(`/api/aide/coding/runs/${encodeURIComponent(runId)}/respond`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ rpc_id: frame.rpcId, ...response }),
    }, 'answer this DSH request');
    if (!receipt.accepted) throw new Error('this request is no longer waiting; reconnect to check its status');
    pendingInteractions.delete(frame.rpcId); responseDrafts.delete(frame.rpcId);
    renderPending(); scheduleLiveRefresh(runId);
    if (selectedRunId === runId) ($('aide-coding-pending').querySelector('button, textarea') || $('aide-coding-detail-title'))?.focus();
  } catch (error) { if (selectedRunId === runId) { setError(error.message); renderPending(); } }
}
function renderPending() {
  const target = $('aide-coding-pending');
  const active = document.activeElement;
  const focusKey = target.contains(active) ? active?.dataset.focusKey : '';
  target.replaceChildren();
  for (const frame of pendingInteractions.values()) {
    const payload = frame.payload;
    const form = element('form', 'acw-pending-request');
    form.addEventListener('submit', event => event.preventDefault());
    if (payload.type === 'approval/requested') {
      form.append(element('h3', '', 'approval needed'), element('p', '', payload.toolName || 'tool'));
      if (payload.reason) form.append(element('p', '', payload.reason));
      const activity = remoteEventCache.get(liveRunId) || [];
      const call = activity.find(event => event.call_id === payload.callId);
      if (call?.arguments) form.append(element('pre', 'acw-output-text', call.arguments));
      else form.append(element('p', 'acw-muted', 'waiting for tool details; refresh or inspect DSH before approving'));
      for (const [label, outcome] of [['allow once', 'allowed-once'], ['reject', 'rejected']]) {
        const button = element('button', 'acw-action', label); button.type = 'button'; button.disabled = !liveReady;
        if (outcome === 'allowed-once' && !call?.arguments) button.disabled = true;
        button.dataset.focusKey = `${frame.rpcId}:${outcome}`;
        button.addEventListener('click', () => respondTo(frame, { outcome }, button)); form.append(button);
      }
    } else {
      form.append(element('h3', '', 'answer needed'));
      let draft = responseDrafts.get(frame.rpcId);
      if (!draft) { draft = {}; responseDrafts.set(frame.rpcId, draft); }
      for (const question of payload.questions || []) {
        const answer = draft[question.id] ||= { selected: [], custom: '' };
        const group = element('fieldset', 'acw-question');
        group.append(element('legend', '', question.question));
        if (question.detail) group.append(element('p', 'acw-muted', question.detail));
        for (const option of question.options || []) {
          const button = element('button', 'acw-action', option.label); button.type = 'button'; button.disabled = !liveReady;
          button.dataset.focusKey = `${frame.rpcId}:${question.id}:${option.label}`;
          button.setAttribute('aria-pressed', String(answer.selected.includes(option.label)));
          if (option.description) button.append(element('span', 'acw-muted', option.description));
          button.addEventListener('click', () => {
            answer.selected = question.multiSelect
              ? (answer.selected.includes(option.label) ? answer.selected.filter(label => label !== option.label) : [...answer.selected, option.label])
              : [option.label];
            if (!question.multiSelect) answer.custom = '';
            renderPending();
          }); group.append(button);
        }
        const label = element('label', '', 'your answer');
        const input = element('textarea', 'acw-question-answer'); input.rows = 2; input.value = answer.custom; input.disabled = !liveReady;
        input.dataset.focusKey = `${frame.rpcId}:${question.id}:custom`;
        input.addEventListener('input', () => {
          answer.custom = input.value;
          if (!question.multiSelect && input.value.trim()) {
            answer.selected = [];
            for (const button of group.querySelectorAll('[aria-pressed]')) button.setAttribute('aria-pressed', 'false');
          }
        }); label.append(input); group.append(label); form.append(group);
      }
      const send = element('button', 'acw-action', 'send answer'); send.type = 'button'; send.disabled = !liveReady;
      send.dataset.focusKey = `${frame.rpcId}:send`;
      send.addEventListener('click', () => {
        const answers = (payload.questions || []).map(question => {
          const answer = draft[question.id], custom = answer.custom.trim();
          return { id: question.id, selected: answer.selected, ...(custom ? { custom } : {}) };
        });
        if (answers.some(answer => !answer.selected.length && !answer.custom)) return setError('answer each question before sending');
        void respondTo(frame, { answers }, send);
      });
      const cancel = element('button', 'acw-action', 'cancel question'); cancel.type = 'button'; cancel.disabled = !liveReady;
      cancel.addEventListener('click', () => respondTo(frame, { cancelled: true }, cancel));
      form.append(send, cancel);
    }
    target.append(form);
  }
  if (focusKey) [...target.querySelectorAll('[data-focus-key]')].find(control => control.dataset.focusKey === focusKey)?.focus();
}
function connectLive(runId) {
  if (liveRunId === runId && liveSource) return;
  closeLive(); pendingInteractions.clear(); renderPending();
  const run = runs.find(item => item.id === runId);
  if (run?.terminal || !connection?.configured) { liveStatus(''); return; }
  liveRunId = runId; liveStatus('connecting to live DSH activity…');
  const source = liveSource = new EventSource(`/api/aide/coding/runs/${encodeURIComponent(runId)}/live`);
  source.onopen = () => {
    if (liveSource !== source) return;
    liveReady = true; pendingInteractions.clear(); renderPending(); liveStatus('live DSH activity'); scheduleLiveRefresh(runId);
  };
  source.onmessage = event => {
    if (liveSource !== source) return;
    let frame; try { frame = JSON.parse(event.data); } catch { return; }
    const payload = frame.payload || {};
    if (['approval/requested', 'question/requested'].includes(payload.type)) { pendingInteractions.set(frame.rpcId, frame); renderPending(); scheduleLiveRefresh(runId); }
    else if (payload.type === 'approval/resolved') {
      for (const [key, pending] of pendingInteractions) if (pending.payload.approvalId === payload.approvalId) pendingInteractions.delete(key);
      renderPending(); scheduleLiveRefresh(runId);
    } else if (payload.type === 'question/resolved') { pendingInteractions.delete(payload.questionRpcId); renderPending(); scheduleLiveRefresh(runId); }
    else if (payload.type === 'session/event' && ['assistant/message', 'tool/call', 'tool/result', 'turn/end'].includes(payload.event?.type)) scheduleLiveRefresh(runId);
  };
  const unavailable = () => { if (liveSource !== source) return; liveReady = false; renderPending(); liveStatus('live connection unavailable; reconnecting. saved results remain available.'); };
  source.onerror = unavailable;
  source.addEventListener('bridge-error', unavailable);
}
function markup() {
  return `
    <div class="acw-toolbar">
      <button type="button" id="aide-coding-back" class="acw-action acw-back">${icon('back')}<span>conversation</span></button>
      <button type="button" id="aide-coding-runs-back" class="acw-action acw-mobile-back">${icon('back')}<span>runs</span></button>
      <span class="acw-toolbar-context">coding</span>
      <button type="button" id="aide-coding-connection-toggle" class="acw-action" aria-expanded="false" aria-controls="aide-coding-connection">${icon('connection')}<span id="aide-coding-connection-label">connection</span></button>
    </div>
    <div class="acw-body">
      <aside class="acw-rail" aria-label="coding runs">
        <div class="acw-rail-head"><h2>runs <span id="aide-coding-run-count"></span></h2><button type="button" id="aide-coding-new" class="acw-icon" aria-label="new coding run" title="new coding run">${icon('plus')}</button></div>
        <div id="aide-coding-run-list"><p class="acw-rail-empty">loading runs…</p></div>
      </aside>
      <div class="acw-main">
        <p id="aide-coding-error" class="acw-error" role="alert" hidden></p>
        <section id="aide-coding-draft" class="acw-content" data-coding-view="draft">
          <h2>new coding run</h2>
          <form id="aide-coding-start" class="acw-start">
            <div class="acw-field"><label id="aide-coding-workspace-label">workspace</label>
              <div class="acw-picker"><button type="button" id="aide-coding-project" aria-labelledby="aide-coding-workspace-label aide-coding-project-title" aria-haspopup="listbox" aria-expanded="false" disabled><span id="aide-coding-project-title">choose workspace</span>${icon('chevron')}</button>
                <div id="aide-coding-workspace-menu" class="acw-workspaces" role="listbox" aria-labelledby="aide-coding-workspace-label" hidden></div>
              </div><p id="aide-coding-project-path" class="acw-path"></p>
            </div>
            <div class="acw-field"><label for="aide-coding-prompt">instruction</label><textarea id="aide-coding-prompt" rows="1" maxlength="50000" data-kokuen-entry="autogrow" placeholder="What should change in this project?" aria-describedby="aide-coding-draft-status" disabled></textarea></div>
            <div class="acw-start-footer"><p id="aide-coding-draft-status" class="acw-muted" role="status">checking connection…</p><button type="submit" id="aide-coding-submit" class="acw-action acw-primary" disabled><span>start in DSH</span>${icon('send')}</button></div>
          </form><button type="button" id="aide-coding-connect-inline" class="acw-action" hidden>connect DSH</button>
        </section>
        <article id="aide-coding-run-detail" class="acw-content aide-coding-run" data-coding-view="run" hidden>
          <div class="acw-detail-meta"><span id="aide-coding-detail-state" class="acw-run-state" role="status"></span><time id="aide-coding-detail-time"></time></div>
          <h2 id="aide-coding-detail-title" tabindex="-1"></h2><p id="aide-coding-detail-path" class="acw-path"></p>
          <div id="aide-coding-run-actions" class="acw-run-actions"></div>
          <p id="aide-coding-live-status" class="acw-muted" role="status"></p><div id="aide-coding-pending" aria-live="polite"></div>
          <section class="acw-result"><h3 id="aide-coding-result-title">status</h3><p id="aide-coding-result-status"></p><p id="aide-coding-result-note" class="acw-muted">Output shows up to 50 recent DSH messages from the last verified refresh.</p></section>
          <section id="aide-coding-output" class="acw-activity" hidden><h3>output and changes</h3><div id="aide-coding-output-body"></div></section>
          <form id="aide-coding-followup" class="acw-start" hidden><div class="acw-field"><label for="aide-coding-followup-prompt">follow-up</label><textarea id="aide-coding-followup-prompt" rows="1" maxlength="50000" data-kokuen-entry="autogrow" placeholder="Continue in this DSH session"></textarea></div><button type="submit" class="acw-action">send follow-up</button></form>
          <section class="acw-activity"><h3>activity</h3><ol id="aide-coding-events" class="aide-coding-events"></ol></section>
          <section id="aide-coding-remote" class="acw-activity" hidden><h3>DSH activity <span class="acw-muted">from last refresh</span></h3><ol id="aide-coding-remote-events"></ol></section>
          <button type="button" id="aide-coding-record-toggle" class="acw-action" aria-expanded="false" aria-controls="aide-coding-record">run details ${icon('chevron')}</button>
          <dl id="aide-coding-record" class="acw-record" hidden><dt>run</dt><dd id="aide-coding-record-id"></dd><dt>DSH session</dt><dd id="aide-coding-record-session"></dd></dl>
        </article>
        <section id="aide-coding-connection" class="acw-content acw-connection" data-coding-view="connection" hidden>
          <button type="button" id="aide-coding-connection-back" class="acw-action">${icon('back')}<span>back to work</span></button>
          <h2>DSH connection</h2><p id="aide-coding-status" role="status">checking connection…</p>
          <div id="aide-coding-install" class="acw-install" hidden>
            <p>DeepSeek Harness isn't installed on this Mac. Alles runs coding work through it.</p>
            <ol class="acw-steps"><li>Get DeepSeek Harness from deepseek.com and open it once.</li><li>Or with Homebrew: <code>brew install --cask deepseek-harness</code></li><li>Come back here and check again.</li></ol>
            <div class="acw-connection-actions"><a class="acw-action acw-primary" href="https://www.deepseek.com/harness/" target="_blank" rel="noopener noreferrer">get DeepSeek Harness</a><button type="button" id="aide-coding-recheck" class="acw-action">check again</button></div>
          </div>
          <form id="aide-coding-pair" class="acw-pair" hidden>
            <div class="acw-field"><label for="aide-coding-url">DSH bridge on this Mac</label><input id="aide-coding-url" name="base_url" type="url" value="http://127.0.0.1:3081" autocomplete="url" spellcheck="false" required></div>
            <div class="acw-field"><label for="aide-coding-code">8-digit code shown by DSH</label><input id="aide-coding-code" name="code" type="text" inputmode="numeric" pattern="[0-9]{8}" maxlength="8" autocomplete="one-time-code" required></div>
            <p class="acw-muted">Pairing lets Alles start and stop coding runs on this Mac. DSH and this Mac must remain available.</p>
            <button type="submit" class="acw-action acw-primary">connect DSH</button>
          </form>
          <div id="aide-coding-ready" hidden><p id="aide-coding-connection-address" class="acw-path"></p><div class="acw-connection-actions"><button type="button" id="aide-coding-check" class="acw-action">check connection</button><button type="button" id="aide-coding-disconnect" class="acw-action">disconnect</button></div><p class="acw-muted">Disconnecting preserves saved runs and does not stop work already running in DSH.</p></div>
        </section>
      </div>
    </div>`;
}
export function initAideCodingWorkspace() {
  const target = $('aide-coding-workspace');
  if (!target || target.tagName === 'BUTTON' || host === target) return;
  host = target; host.classList.add('aide-coding-workspace'); host.setAttribute('aria-label', 'coding workspace'); host.dataset.pane = 'detail';
  host.innerHTML = markup(); wireAutosizeTextarea($('aide-coding-prompt'));
  wireAutosizeTextarea($('aide-coding-followup-prompt'));
  $('aide-coding-followup').addEventListener('submit', async event => {
    event.preventDefault();
    const runId = selectedRunId, prompt = $('aide-coding-followup-prompt').value.trim();
    if (followingUp || !prompt || !runId) return;
    const previous = followupRequests.get(runId);
    const request = previous?.prompt === prompt ? previous : { request_id: requestId(), prompt };
    followupRequests.set(runId, request); followingUp = true;
    const button = event.currentTarget.querySelector('button[type="submit"]'); button.disabled = true; setError();
    try {
      await api(`/api/aide/coding/runs/${encodeURIComponent(runId)}/continue`, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(request),
      }, 'continue this DSH session');
      followupRequests.delete(runId);
      if (followupDrafts.get(runId)?.trim() === prompt) followupDrafts.delete(runId);
      if (selectedRunId === runId && $('aide-coding-followup-prompt').value.trim() === prompt) $('aide-coding-followup-prompt').value = '';
      await loadRuns(); await loadEvents(runId);
      if (selectedRunId === runId) { connectLive(runId); $('aide-coding-detail-title').focus(); }
    } catch (error) { if (selectedRunId === runId) setError(`${error.message}. retry the same follow-up to check its saved request.`); }
    finally { followingUp = false; button.disabled = false; }
  });
  $('aide-coding-back').addEventListener('click', () => { closeAideCodingWorkspace(); host.dispatchEvent(new CustomEvent('aide-coding-close', { bubbles: true })); });
  $('aide-coding-new').addEventListener('click', () => {
    if (selectedRunId) followupDrafts.set(selectedRunId, $('aide-coding-followup-prompt').value);
    selectionVersion++; selectedRunId = null; setView('draft', { focus: true }); renderRuns();
  });
  $('aide-coding-runs-back').addEventListener('click', () => setView('runs', { focus: true }));
  $('aide-coding-connection-toggle').addEventListener('click', showConnection);
  $('aide-coding-connect-inline').addEventListener('click', showConnection);
  $('aide-coding-connection-back').addEventListener('click', () => { setView(previousView); $('aide-coding-connection-toggle').focus(); });
  $('aide-coding-record-toggle').addEventListener('click', event => { const open = $('aide-coding-record').hidden; $('aide-coding-record').hidden = !open; event.currentTarget.setAttribute('aria-expanded', String(open)); });
  $('aide-coding-pair').addEventListener('submit', async event => {
    event.preventDefault(); const button = event.currentTarget.querySelector('button[type="submit"]'); button.disabled = true; setError();
    $('aide-coding-connection-back').focus();
    try {
      const status = await api('/api/aide/coding/pair', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ base_url: $('aide-coding-url').value.trim(), code: $('aide-coding-code').value.trim() }) }, 'pair DSH');
      $('aide-coding-code').value = ''; setConnectionState(status); await loadWorkspaces();
      if (currentView === 'connection') $('aide-coding-connection-back').focus();
    } catch (error) { setStatus(error.message, 'error'); } finally { button.disabled = false; }
  });
  $('aide-coding-start').addEventListener('submit', async event => {
    event.preventDefault(); const prompt = $('aide-coding-prompt').value.trim();
    if (submitting) return;
    if (!selectedWorkspace) return setError('Choose a DSH workspace.');
    if (!prompt) { setError('Write a coding instruction.'); $('aide-coding-prompt').focus(); return; }
    const payload = { aide_session_id: window._currentSession?.id || null, workspace_id: selectedWorkspace.workspace_id, workspace_path: selectedWorkspace.path || '', prompt };
    const key = JSON.stringify(payload);
    if (!pendingStart || pendingStart.key !== key) pendingStart = { key, id: requestId() };
    const identity = pendingStart.id;
    const version = selectionVersion, view = currentView, surface = host;
    const ownsSurface = () => selectionVersion === version && currentView === view && host === surface && !host.hidden;
    submitting = true;
    const button = $('aide-coding-submit'); button.disabled = true; button.setAttribute('aria-busy', 'true'); setError();
    try {
      let run;
      try {
        run = await api('/api/aide/coding/runs', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ request_id: identity, ...payload }) }, 'start a DSH coding run');
      } catch (error) {
        try { run = await api(`/api/aide/coding/runs/${encodeURIComponent(identity)}`, {}, 'check the saved coding request'); }
        catch { throw error; }
      }
      if ($('aide-coding-prompt').value.trim() === prompt) $('aide-coding-prompt').value = '';
      pendingStart = null; autosizeTextarea($('aide-coding-prompt')); await loadRuns();
      if (ownsSurface()) await selectRun(run.id, { focus: true });
    } catch (error) { if (ownsSurface()) setError(`${error.message} Retry this unchanged instruction to check the same request.`); await loadRuns().catch(() => {}); }
    finally { submitting = false; button.disabled = !connection?.configured || !selectedWorkspace; button.removeAttribute('aria-busy'); }
  });
  $('aide-coding-project').addEventListener('click', () => {
    const menu = $('aide-coding-workspace-menu'), open = menu.hidden; menu.hidden = !open; $('aide-coding-project').setAttribute('aria-expanded', String(open));
    if (open) menu.querySelector('[aria-selected="true"], [role="option"]')?.focus();
  });
  $('aide-coding-workspace-menu').addEventListener('keydown', event => {
    const options = [...event.currentTarget.querySelectorAll('[role="option"]')], index = options.indexOf(document.activeElement);
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeWorkspaceMenu({ focus: true }); }
    else if (options.length && ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault(); options[event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length].focus();
    }
  });
  $('aide-coding-recheck').addEventListener('click', () => loadStatus());
  $('aide-coding-check').addEventListener('click', async event => {
    const button = event.currentTarget; button.disabled = true; setStatus('checking DSH…');
    $('aide-coding-connection-back').focus();
    try { setConnectionState(await api('/api/aide/coding/health', { method: 'POST' }, 'check DSH')); await loadWorkspaces(); }
    catch (error) { setStatus('DSH is unavailable. Saved runs are unchanged.', 'warning'); }
    finally { button.disabled = false; if (currentView === 'connection') button.focus(); }
  });
  $('aide-coding-disconnect').addEventListener('click', async event => {
    const button = event.currentTarget; button.disabled = true; setError();
    $('aide-coding-connection-back').focus();
    try {
      await api('/api/aide/coding/connection', { method: 'DELETE' }, 'disconnect DSH');
      selectedWorkspace = null; workspaces = []; updateWorkspace(); await loadStatus();
      if (currentView === 'connection') $('aide-coding-url').focus();
    }
    catch (error) { setError(error.message); } finally { button.disabled = false; }
  });
  $('aide-coding-run-actions').addEventListener('click', async event => {
    const button = event.target.closest('[data-run-action]'); if (!button) return;
    const { runId, runAction: action } = button.dataset;
    for (const sibling of event.currentTarget.querySelectorAll('button')) sibling.disabled = true;
    button.setAttribute('aria-busy', 'true'); setError();
    try { await runMutation(runId, action); } catch (error) { setError(error.message); }
    finally {
      for (const sibling of $('aide-coding-run-actions').querySelectorAll('button')) sibling.disabled = false;
      button.removeAttribute('aria-busy');
      if (currentView === 'run' && selectedRunId === runId) $('aide-coding-run-actions').querySelector(`[data-run-action="${action}"]`)?.focus();
    }
  });
  host.addEventListener('keydown', event => { if (event.key === 'Escape' && currentView === 'connection') { event.preventDefault(); event.stopPropagation(); setView(previousView); $('aide-coding-connection-toggle').focus(); } });
  document.addEventListener('click', event => { if (!event.composedPath().includes($('aide-coding-project')?.parentElement)) closeWorkspaceMenu(); });
  window.matchMedia('(max-width: 620px)').addEventListener('change', event => {
    if (!event.matches && currentView === 'runs') {
      if (selectedRunId) void selectRun(selectedRunId);
      else setView('draft');
    }
  });
}
export function openAideCodingWorkspace({ refresh = true } = {}) {
  initAideCodingWorkspace(); if (!host) return Promise.resolve();
  host.hidden = false; if (currentView === 'draft') autosizeTextarea($('aide-coding-prompt'));
  if (!refresh) { if (currentView === 'run' && selectedRunId) connectLive(selectedRunId); return Promise.resolve(); }
  if (!opening) opening = loadStatus().finally(() => { opening = null; }); return opening;
}
export function closeAideCodingWorkspace() { selectionVersion++; if (host) host.hidden = true; closeWorkspaceMenu(); closeLive(); }
// Compatibility entry points for the Aide task-tools integration.
export const initAideCoding = initAideCodingWorkspace;
export const openAideCoding = openAideCodingWorkspace;
export const mountAideCodingPanel = initAideCodingWorkspace;

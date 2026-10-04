import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';
import { getDropdownValue, populateDropdown } from './dropdown.js?v=212';
import { t as tr } from './i18n.js';
import { createFocusBoundary, setControlState } from './kokuen.js?v=1';
import { toast } from './util.js';
const _si = n => (window.icon ? window.icon(n) : '');   // central icon set, load-order safe

let _tasks = [];
let _tree = [];
let _tab = 'active';   // 'active' | 'done' (history)
let _search = '';
let _tabsWired = false;
let _loadGeneration = 0;
let _recoveryChecked = false;
let _draftScopes = [];
let _closeEditor = null;
let _editorGeneration = 0;
const TASK_DRAFT_PREFIX = 'alles.tasks.draft.v1:';

function taskValues(task) {
  return {
    title: String(task.title || '').trim(), notes: String(task.notes || ''),
    priority: Number(task.priority) || 0, repeat: String(task.repeat || '').trim(),
    due_date: String(task.due_date || '').trim() || null,
    tags: (Array.isArray(task.tags) ? task.tags : String(task.tags || '').split(','))
      .map(value => value.trim()).filter(Boolean).join(','),
    project: String(task.project || '').trim(),
  };
}

function taskChanges(base, values) {
  return Object.fromEntries(Object.entries(values).filter(([field, value]) => value !== base[field]));
}

async function draftScopes() {
  try {
    const response = await fetch('/api/tasks/draft-scope', { cache: 'no-store' });
    if (!response.ok) return [];
    const { scopes } = await response.json();
    return Array.isArray(scopes) ? scopes.filter(scope => typeof scope === 'string' && /^[a-f0-9]{64}$/.test(scope)) : [];
  } catch { return []; }
}

function draftKey(scope, id) { return `${TASK_DRAFT_PREFIX}${scope}:${id}`; }
function validDraftValues(value) {
  return value && ['title', 'notes', 'repeat', 'tags', 'project'].every(field => typeof value[field] === 'string')
    && Number.isInteger(value.priority) && (value.due_date === null || typeof value.due_date === 'string');
}
function readTaskDraft(id, scopes = _draftScopes) {
  for (const scope of scopes) {
    try {
      const draft = JSON.parse(sessionStorage.getItem(draftKey(scope, id)) || 'null');
      if (draft?.version === 1 && draft.id === id && draft.scope === scope
          && validDraftValues(draft.base) && validDraftValues(draft.values)) return draft;
    } catch { /* Keep editing available; persistTaskDraft reports storage failure. */ }
  }
  return null;
}

function persistTaskDraft(id, base, values) {
  const scope = _draftScopes[0];
  if (!scope) return false;
  try {
    const key = draftKey(scope, id);
    const data = JSON.stringify({ version: 1, scope, id, base, values });
    sessionStorage.setItem(key, data);
    return sessionStorage.getItem(key) === data;
  } catch { return false; }
}

function clearTaskDraft(id) {
  try {
    for (const scope of _draftScopes) sessionStorage.removeItem(draftKey(scope, id));
    return true;
  } catch { return false; }
}

async function recoverTaskDraft(generation) {
  if (_recoveryChecked || document.querySelector('.task-editor-ov')) return;
  const editorGeneration = _editorGeneration;
  const scopes = await draftScopes();
  if (generation !== _loadGeneration || editorGeneration !== _editorGeneration || !scopes.length) return;
  _draftScopes = scopes;
  _recoveryChecked = true;
  try {
    for (let index = 0; index < sessionStorage.length; index++) {
      const key = sessionStorage.key(index);
      const scope = scopes.find(value => key?.startsWith(`${TASK_DRAFT_PREFIX}${value}:`));
      if (!scope) continue;
      const id = key.slice(`${TASK_DRAFT_PREFIX}${scope}:`.length);
      const draft = readTaskDraft(id, scopes);
      if (draft) { await openTaskEditor(id, null, draft); break; }
    }
  } catch { /* An editor still offers export and an unload guard when storage is unavailable. */ }
}


function _wireTabs() {
  if (_tabsWired) return; _tabsWired = true;
  document.querySelectorAll('.tasks-tab').forEach(b => b.addEventListener('click', () => {
    ++_loadGeneration;
    _tab = b.dataset.tab;
    document.querySelectorAll('.tasks-tab').forEach(x => {
      const selected = x === b;
      x.classList.toggle('active', selected);
      x.setAttribute('aria-pressed', String(selected));
    });
    loadTasks();
  }));
  const si = document.getElementById('tasks-search');
  let _t = 0;
  si?.addEventListener('input', () => {
    ++_loadGeneration;
    clearTimeout(_t);
    _t = setTimeout(() => { _search = si.value.trim(); loadTasks(); }, 180);
  });
  window.addEventListener('alles:localization-change', () => {
    if (_tab === 'active' && !_search) renderTree();
    else renderTasks();
  });
}

const _URL = { active: '/api/tasks', done: '/api/tasks/done',
               today: '/api/tasks/views/today', upcoming: '/api/tasks/views/upcoming',
               someday: '/api/tasks/views/someday' };

export async function loadTasks(fetcher = fetch, target = null) {
  _wireTabs();
  const generation = ++_loadGeneration;
  const tab = _tab, search = _search;
  const isTree = tab === 'active' && !search;
  const url = search ? `/api/tasks/search?q=${encodeURIComponent(search)}&view=${encodeURIComponent(tab)}`
                     : (isTree ? '/api/tasks/tree' : (_URL[tab] || '/api/tasks'));
  let data;
  try {
    const response = await fetcher(url);
    if (!response.ok) throw new Error(`request failed (${response.status})`);
    data = await response.json();
  } catch (error) {
    if (generation !== _loadGeneration) return;
    throw error;
  }
  if (generation !== _loadGeneration || tab !== _tab || search !== _search) return;
  if (isTree) { _tree = data; renderTree(); } else { _tasks = data; renderTasks(); }
  if (target?.view === 'tasks' && isTree && !_findTask(target.id)) {
    const response = await fetcher('/api/tasks/done');
    if (!response.ok) throw new Error(`request failed (${response.status})`);
    const completed = await response.json();
    if (generation !== _loadGeneration || tab !== _tab || search !== _search) return;
    if (completed.some(task => task.id === target.id)) {
      _tab = 'done'; _tasks = completed;
      document.querySelectorAll('.tasks-tab').forEach(button => {
        const selected = button.dataset.tab === _tab;
        button.classList.toggle('active', selected);
        button.setAttribute('aria-pressed', String(selected));
      });
      renderTasks();
    }
  }
  // Exact links open their own draft; other retained drafts stay available by task.
  if (target?.view !== 'tasks') await recoverTaskDraft(generation);
}

function _todayISO() { return new Date().toISOString().slice(0, 10); }

function _dueBadge(d) {
  if (!d) return '';
  const iso = d.slice(0, 10), today = _todayISO();
  const cls = iso < today ? 'task-due overdue' : (iso === today ? 'task-due today' : 'task-due');
  const label = iso === today ? tr('common.today') : (iso === _shift(today, 1) ? tr('tasks.tomorrow') : iso);
  return `<span class="${cls}">${label}</span>`;
}
function _shift(iso, n) { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }

function _rowHtml(t, child, progress) {
  const title = esc(t.title);
  const checkLabel = esc(tr(t.done ? 'tasks.mark_incomplete' : 'tasks.mark_complete', { task: t.title }));
  return `
    <div class="task-item${child ? ' task-child' : ''}" data-id="${t.id}">
      <button type="button" class="task-check${t.done ? ' done' : ''}" data-id="${t.id}" aria-label="${checkLabel}"></button>
      <div class="task-content">
      <button type="button" class="task-title${t.done ? ' done' : ''}" aria-label="${esc(tr('tasks.edit_named', { task: t.title }))}">${title}</button>
      <div class="task-meta">
      ${t.repeat ? `<span class="task-repeat" title="${esc(tr('tasks.repeats', { repeat: tr(`tasks.repeat.${t.repeat}`) }))}">${_si('refresh')}</span>` : ''}
      ${_dueBadge(t.due_date)}
      ${(t.tags || []).map(g => `<span class="task-tag">#${esc(g)}</span>`).join('')}
      ${t.priority ? `<span class="task-high task-p${t.priority}">${esc(tr(`tasks.priority.${['', 'low', 'medium', 'high'][t.priority] || 'high'}`))}</span>` : ''}
      ${progress && progress.total ? `<span class="task-progress">${progress.done}/${progress.total}</span>` : ''}
      </div>
      </div>
      <div class="task-actions">
      ${!child ? `<button type="button" class="task-addsub" data-id="${t.id}" aria-label="${esc(tr('tasks.add_subtask_named', { task: t.title }))}" title="${esc(tr('tasks.add_subtask'))}">${esc(tr('tasks.sub'))}</button>` : ''}
      <button type="button" class="task-del" data-id="${t.id}" aria-label="${esc(tr('tasks.delete_named', { task: t.title }))}">×</button>
      </div>
    </div>`;
}

function _emptyMsg() {
  const msg = _tab === 'done' ? tr('tasks.no_completed') : tr('tasks.nothing_here');
  return `<div style="padding:1rem 0;font-size:0.75rem;color:var(--muted)">${msg}</div>`;
}

function renderTasks() {
  const list = document.getElementById('tasks-list');
  if (!list) return;
  list.innerHTML = _tasks.length ? _tasks.map(t => _rowHtml(t, false)).join('') : _emptyMsg();
  _wireRows(list);
}

function renderTree() {
  const list = document.getElementById('tasks-list');
  if (!list) return;
  list.innerHTML = _tree.length
    ? _tree.map(t => _rowHtml(t, false, t.progress) + (t.subtasks || []).map(s => _rowHtml(s, true)).join('')).join('')
    : _emptyMsg();
  _wireRows(list);
}

function _findTask(id) {
  const visible = _tab === 'active' && !_search ? _tree : _tasks;
  for (const t of visible) {
    if (t.id === id) return t;
    for (const s of (t.subtasks || [])) if (s.id === id) return s;
  }
  return null;
}

function _wireRows(list) {
  list.querySelectorAll('.task-check').forEach(btn => btn.addEventListener('click', async () => {
    if (btn.getAttribute('aria-busy') === 'true') return;
    const t = _findTask(btn.dataset.id);
    await _mutateTask(btn, async () => {
      await _requireOk(fetch(`/api/tasks/${btn.dataset.id}`, {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ done: !(t && t.done) }),
      }));
      await loadTasks();
    }, { failureMessage: tr(t?.done ? 'tasks.reopen_failed' : 'tasks.completion_failed') });
  }));
  list.querySelectorAll('.task-del').forEach(btn => btn.addEventListener('click', async () => {
    if (btn.getAttribute('aria-busy') === 'true') return;
    await _mutateTask(btn, async () => {
      await _requireOk(fetch(`/api/tasks/${btn.dataset.id}`, { method: 'DELETE' }));
      await loadTasks();
    });
  }));
  list.querySelectorAll('.task-addsub').forEach(btn => btn.addEventListener('click', async () => {
    if (btn.getAttribute('aria-busy') === 'true') return;
    setControlState(btn, 'busy', { message: tr('tasks.waiting_for_subtask') });
    const title = await dlgPrompt(tr('tasks.subtask_prompt'));
    if (!title?.trim()) {
      btn.removeAttribute('aria-busy');
      setControlState(btn, 'resting');
      return;
    }
    await _mutateTask(btn, async () => {
      await _requireOk(fetch('/api/tasks', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), parent_id: btn.dataset.id }),
      }));
      await loadTasks();
    }, { alreadyBusy: true });
  }));
  list.querySelectorAll('.task-title').forEach(el => el.addEventListener('click', () => {
    openTaskEditor(el.closest('.task-item').dataset.id, el);
  }));
}

async function _requireOk(responsePromise) {
  const response = await responsePromise;
  if (!response.ok) throw new Error(`request failed (${response.status})`);
  return response;
}

async function _mutateTask(button, action, { alreadyBusy = false, failureMessage = tr('common.request_failed') } = {}) {
  if (!alreadyBusy) setControlState(button, 'busy', { message: tr('common.saving') });
  button.disabled = true;
  button.setAttribute('aria-disabled', 'true');
  try {
    await action();
    return true;
  } catch {
    button.disabled = false;
    button.removeAttribute('aria-disabled');
    button.removeAttribute('aria-busy');
    setControlState(button, 'error', { message: failureMessage });
    toast(failureMessage, 'error');
    return false;
  }
}

export async function prepareTaskNavigation() {
  ++_editorGeneration;
  return !_closeEditor || Boolean(await _closeEditor({ restoreFocus: false }));
}

export async function openTaskRecord(id, isCurrent = () => true) {
  const existing = document.querySelector('.task-editor-ov');
  if (existing) return existing.dataset.taskId === id;
  if (!_findTask(id) && (_tab !== 'active' || _search)) {
    _tab = 'active';
    _search = '';
    const search = document.getElementById('tasks-search');
    if (search) search.value = '';
    document.querySelectorAll('.tasks-tab').forEach(button => {
      const selected = button.dataset.tab === _tab;
      button.classList.toggle('active', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
    await loadTasks(fetch, { view: 'tasks', id });
  }
  if (!isCurrent() || !_findTask(id) || document.querySelector('.task-editor-ov')) return false;
  const row = [...document.querySelectorAll('#tasks-list .task-item')].find(item => item.dataset.id === id);
  const source = row?.querySelector('.task-title');
  source?.scrollIntoView({ block: 'center', behavior: 'instant' });
  await openTaskEditor(id, source, null, isCurrent);
  return document.querySelector('.task-editor-ov')?.dataset.taskId === id;
}

async function openTaskEditor(id, source, recovered = null, isCurrent = () => true) {
  if (document.querySelector('.task-editor-ov')) return;
  const generation = _editorGeneration;
  const scopes = await draftScopes();
  if (generation !== _editorGeneration || !isCurrent() || document.querySelector('.task-editor-ov') || (source && !source.getClientRects().length)) return;
  _draftScopes = scopes;
  recovered = readTaskDraft(id, scopes) || (recovered && scopes.includes(recovered.scope) ? recovered : null);
  const savedTask = _findTask(id);
  if (!savedTask && !recovered) return;
  let base = taskValues(recovered?.base || savedTask);
  let values = taskValues(recovered?.values || savedTask);
  if (recovered && savedTask) {
    const latest = taskValues(savedTask);
    for (const field of Object.keys(base)) {
      if (values[field] === base[field]) base[field] = values[field] = latest[field];
    }
  }
  const t = { ...values, id, tags: values.tags.split(',').filter(Boolean) };
  const priorities = [[0, tr('tasks.priority.none')], [1, tr('tasks.priority.low')], [2, tr('tasks.priority.medium')], [3, tr('tasks.priority.high')]];
  const repeats = [['', tr('tasks.repeat.none')], ['daily', tr('tasks.repeat.daily')], ['weekly', tr('tasks.repeat.weekly')], ['monthly', tr('tasks.repeat.monthly')], ['yearly', tr('tasks.repeat.yearly')]];
  const ov = document.createElement('div');
  ov.className = 'task-editor-ov';
  ov.dataset.taskId = id;
  ov.innerHTML = `<div class="task-editor" role="dialog" aria-modal="true" aria-labelledby="task-editor-title">
    <h2 class="sr-only" id="task-editor-title">${esc(tr('tasks.edit_dialog'))}</h2>
    <label class="sr-only" for="te-title">${esc(tr('tasks.title_label'))}</label><input class="settings-input" id="te-title" value="${esc(t.title)}">
    <label class="sr-only" for="te-notes">${esc(tr('tasks.notes'))}</label><textarea class="settings-input te-notes" id="te-notes" placeholder="${esc(tr('tasks.notes'))}">${esc(t.notes || '')}</textarea>
    <div class="te-row"><label id="te-prio-label">${esc(tr('tasks.priority.label'))}</label><div class="settings-input custom-select" id="te-prio" aria-labelledby="te-prio-label"></div></div>
    <div class="te-row"><label id="te-rep-label">${esc(tr('tasks.repeat.label'))}</label><div class="settings-input custom-select" id="te-rep" aria-labelledby="te-rep-label"></div></div>
    <div class="te-row"><label for="te-due">${esc(tr('tasks.due'))}</label><input class="settings-input" id="te-due" value="${esc(t.due_date || '')}" placeholder="YYYY-MM-DD"></div>
    <div class="te-resched">${['today', 'tomorrow', 'next_week', 'weekend'].map(w => `<button class="btn te-rs" data-w="${w}">${esc(tr(`tasks.reschedule.${w}`))}</button>`).join('')}</div>
    <div class="te-row"><label for="te-tags">${esc(tr('tasks.tags'))}</label><input class="settings-input" id="te-tags" value="${esc((t.tags || []).join(', '))}" placeholder="${esc(tr('tasks.tags_placeholder'))}"></div>
    <div class="te-row"><label for="te-proj">${esc(tr('tasks.project'))}</label><input class="settings-input" id="te-proj" value="${esc(t.project || '')}"></div>
    <div class="task-recovery" hidden>
      <p class="task-recovery-message" role="status" tabindex="-1"></p>
      <div class="task-conflict-values" hidden></div>
      <div class="task-recovery-actions">
        <button type="button" class="btn" data-task-recovery="export">${esc(tr('tasks.download_draft'))}</button>
        <button type="button" class="btn" data-task-recovery="saved" hidden>${esc(tr('tasks.use_saved'))}</button>
        <button type="button" class="btn" data-task-recovery="mine" hidden>${esc(tr('tasks.keep_changes'))}</button>
      </div>
    </div>
    ${savedTask?.source?.kind === 'mail' ? '<button type="button" class="btn" id="te-source">open original message</button>' : ''}
    ${savedTask?.source?.kind === 'aide' ? `<details class="capture-source"><summary>${savedTask.source.private ? 'private Aide reply' : 'original Aide reply'}</summary><pre>${esc(savedTask.source.excerpt)}</pre></details>${savedTask.source.private ? '' : '<button type="button" class="btn" id="te-source">open original reply</button>'}` : ''}
    ${savedTask?.source?.kind === 'capture' ? `<details class="capture-source"><summary>original capture</summary><pre>${esc(savedTask.source.excerpt)}</pre></details>` : ''}
    <div class="te-actions"><button type="button" class="btn" id="te-cancel">${esc(tr('common.cancel'))}</button><button type="button" class="btn primary" id="te-save">${esc(tr('common.save'))}</button></div>
  </div>`;
  document.body.appendChild(ov);
  populateDropdown(ov.querySelector('#te-prio'), priorities.map(([value, label]) => ({ value, label })), t.priority || 0);
  populateDropdown(ov.querySelector('#te-rep'), repeats.map(([value, label]) => ({ value, label })), t.repeat || '');
  const dialog = ov.querySelector('.task-editor');
  let focusBoundary = null;
  let saving = false;
  let confirmingClose = false;
  let latestConflict = null;
  let hasStoredDraft = Boolean(recovered);
  let storageFailed = false;
  const recovery = dialog.querySelector('.task-recovery');
  const message = recovery.querySelector('.task-recovery-message');
  const mine = recovery.querySelector('[data-task-recovery="mine"]');
  const useSaved = recovery.querySelector('[data-task-recovery="saved"]');
  const conflictValues = recovery.querySelector('.task-conflict-values');
  const readValues = () => ({
    title: ov.querySelector('#te-title').value.trim() || base.title,
    notes: ov.querySelector('#te-notes').value,
    priority: parseInt(getDropdownValue(ov.querySelector('#te-prio'))) || 0,
    repeat: getDropdownValue(ov.querySelector('#te-rep')),
    due_date: ov.querySelector('#te-due').value.trim() || null,
    tags: ov.querySelector('#te-tags').value.split(',').map(s => s.trim()).filter(Boolean).join(','),
    project: ov.querySelector('#te-proj').value.trim(),
  });
  const isDirty = () => Object.keys(taskChanges(base, readValues())).length > 0;
  function showRecovery(text) {
    recovery.hidden = false;
    message.textContent = text;
  }
  function putValues(next) {
    for (const [field, selector] of Object.entries({ title: '#te-title', notes: '#te-notes', due_date: '#te-due', tags: '#te-tags', project: '#te-proj' })) {
      ov.querySelector(selector).value = next[field] ?? '';
    }
    populateDropdown(ov.querySelector('#te-prio'), priorities.map(([value, label]) => ({ value, label })), next.priority);
    populateDropdown(ov.querySelector('#te-rep'), repeats.map(([value, label]) => ({ value, label })), next.repeat);
  }
  function storeDraft() {
    if (!isDirty()) {
      if (hasStoredDraft && !clearTaskDraft(id)) {
        storageFailed = true;
        showRecovery(tr('tasks.draft_cleanup_failed'));
        return false;
      }
      hasStoredDraft = false;
      storageFailed = false;
      if (!latestConflict && !recovery.hidden) showRecovery(tr('tasks.no_changes'));
      return true;
    }
    const stored = persistTaskDraft(id, base, readValues());
    hasStoredDraft ||= stored;
    storageFailed = !stored;
    if (!stored) showRecovery(tr('tasks.draft_storage_failed'));
    else if (!latestConflict) showRecovery(tr(recovered ? 'tasks.draft_recovered' : 'tasks.draft_kept'));
    return stored;
  }
  const unload = event => {
    if (isDirty() && !storeDraft()) { event.preventDefault(); event.returnValue = ''; }
  };
  window.addEventListener('beforeunload', unload);
  dialog.addEventListener('input', storeDraft);
  dialog.addEventListener('change', storeDraft);
  const confirm = async text => {
    if (confirmingClose) return false;
    const previousFocus = document.activeElement;
    confirmingClose = true;
    dialog.inert = true;
    try { return await dlgConfirm(text); }
    finally { dialog.inert = false; confirmingClose = false; previousFocus?.focus(); }
  };
  const close = async ({ restoreFocus = true, discard = false } = {}) => {
    if (saving || confirmingClose) return;
    if (!discard && isDirty() && !(await confirm(tr('tasks.discard_changes')))) return;
    if (hasStoredDraft && !clearTaskDraft(id)) {
      showRecovery(tr('tasks.draft_cleanup_failed'));
      message.focus();
      return;
    }
    window.removeEventListener('beforeunload', unload);
    focusBoundary?.deactivate({ restoreFocus });
    focusBoundary?.destroy();
    ov.remove();
    _closeEditor = null;
    return true;
  };
  _closeEditor = close;
  focusBoundary = createFocusBoundary(dialog, { trigger: source, onEscape: close });
  ov.addEventListener('click', e => { if (e.target === ov) close(); });
  ov.querySelector('#te-cancel').onclick = close;
  ov.querySelector('#te-source')?.addEventListener('click', async () => {
    if (!(await close({ restoreFocus: false }))) return;
    if (savedTask.source.kind === 'mail') await window._openRecord?.('mail', `task-${id}`);
    else if (!(await window._openSearchResult?.('chat', savedTask.source.session_id, savedTask.source.message_id))) {
      toast('could not open the original reply', 'error');
    }
  });
  ov.querySelectorAll('.te-rs').forEach(b => b.addEventListener('click', () => {
    ov.querySelector('#te-due').value = _reschedDate(b.dataset.w);
    storeDraft();
  }));
  recovery.querySelector('[data-task-recovery="export"]').onclick = () => {
    const blob = new Blob([JSON.stringify({ id, base, draft: readValues(), saved: latestConflict }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = `alles-task-${id}-draft.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const resetConflict = () => {
    latestConflict = null;
    mine.hidden = useSaved.hidden = conflictValues.hidden = true;
  };
  useSaved.onclick = async () => {
    if (!(await confirm(tr('tasks.discard_for_saved')))) return;
    base = taskValues(latestConflict);
    putValues(base);
    resetConflict(); storeDraft();
    if (!storageFailed) showRecovery(tr('tasks.saved_loaded'));
    ov.querySelector('#te-notes').focus();
  };
  mine.onclick = async () => {
    if (!(await confirm(tr('tasks.replace_conflicts')))) return;
    const changes = taskChanges(base, readValues());
    base = taskValues(latestConflict);
    putValues({ ...base, ...changes });
    resetConflict(); storeDraft();
    if (!storageFailed) showRecovery(tr('tasks.conflict_reviewed'));
    ov.querySelector('#te-save').focus();
  };
  ov.querySelector('#te-save').onclick = async event => {
    if (saving) return;
    const values = readValues();
    const changes = taskChanges(base, values);
    if (!Object.keys(changes).length) { await close({ discard: true }); return; }
    storeDraft();
    const body = { ...changes, expected: Object.fromEntries(Object.keys(changes).map(field => [field, base[field]])) };
    if (_draftScopes[0]) body.draft_scope = _draftScopes[0];
    const saveButton = event.currentTarget;
    saving = true;
    const controls = [...dialog.querySelectorAll('input, textarea, button, .custom-select')];
    const disabledBefore = controls.map(control => control.disabled);
    for (const control of controls) control.disabled = true;
    dialog.setAttribute('aria-busy', 'true'); dialog.tabIndex = -1; dialog.focus();
    setControlState(saveButton, 'busy', { message: tr('common.saving') });
    saveButton.textContent = tr('common.saving');
    saveButton.setAttribute('aria-disabled', 'true');
    let saved = false;
    try {
      const response = await fetch(`/api/tasks/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
      const result = await response.json();
      if (response.status === 409 && result.detail?.code === 'task_conflict') {
        latestConflict = result.detail.current;
        showRecovery(tr('tasks.conflict_message'));
        conflictValues.innerHTML = result.detail.fields.map(field => `<div><strong>${esc(tr(({ title: 'tasks.title_label', notes: 'tasks.notes', priority: 'tasks.priority.label', repeat: 'tasks.repeat.label', due_date: 'tasks.due', tags: 'tasks.tags', project: 'tasks.project' })[field]))}</strong><p>${esc(tr('tasks.your_change'))}: ${esc(values[field] ?? '')}</p><p>${esc(tr('tasks.saved_value'))}: ${esc(taskValues(latestConflict)[field] ?? '')}</p></div>`).join('');
        mine.hidden = useSaved.hidden = conflictValues.hidden = false;
      } else if (!response.ok) throw new Error('request failed');
      else if (result.queued) showRecovery(tr('tasks.save_queued'));
      else {
        base = taskValues(result); putValues(base); saved = true;
      }
    } catch {
      showRecovery(tr('tasks.save_not_confirmed'));
    } finally {
      saving = false;
      controls.forEach((control, index) => { control.disabled = disabledBefore[index]; });
      dialog.removeAttribute('aria-busy');
      saveButton.textContent = tr('common.save');
      saveButton.removeAttribute('aria-disabled'); saveButton.removeAttribute('aria-busy');
      setControlState(saveButton, saved ? 'resting' : 'error', { message: saved ? '' : message.textContent });
    }
    if (saved) {
      if (await close({ restoreFocus: false, discard: true })) {
        try { await loadTasks(); }
        catch { toast(tr('tasks.saved_refresh_failed'), 'error'); }
        document.querySelector(`.task-item[data-id="${id}"] .task-title`)?.focus();
      } else { message.focus(); }
    } else { message.focus(); }
  };
  if (recovered) showRecovery(tr('tasks.draft_recovered'));
  if (isDirty()) storeDraft();
  focusBoundary.activate({ focus: ov.querySelector('#te-title'), source });
}

// quick-reschedule date, computed locally to mirror services/task_nl.reschedule_date
function _reschedDate(w) {
  const d = new Date(); d.setHours(0, 0, 0, 0);
  if (w === 'tomorrow') d.setDate(d.getDate() + 1);
  else if (w === 'next_week') d.setDate(d.getDate() + 7);
  else if (w === 'weekend') d.setDate(d.getDate() + ((6 - d.getDay() + 7) % 7));  // next Saturday (today if Sat)
  const z = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}

export async function addTask(title) {
  if (!title.trim()) return;
  // natural-language quick add — parses due date / repeat / #tags / ! priority
  await fetch('/api/tasks/quick', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text: title }),
  });
  if (_tab === 'done') {   // jump back to a visible list so the new task shows
    _tab = 'active';
    document.querySelectorAll('.tasks-tab').forEach(x => {
      const selected = x.dataset.tab === 'active';
      x.classList.toggle('active', selected);
      x.setAttribute('aria-pressed', String(selected));
    });
  }
  if (_search) {   // a stale search filter would hide the new task — clear it like the done-tab case
    _search = '';
    const si = document.getElementById('tasks-search');
    if (si) si.value = '';
  }
  await loadTasks();
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

import { mdToHtml, plainError, toast, withoutThinking, writeClipboard } from './util.js';
import { renderDiff } from './agentview.js';
import {
  appendUserMsg, appendInterruptionNotice, createStreamingAiRow, scrollDown, wireMessageActions, rereadActiveSession, markRead, addStepsAction, openReplySteps,
  showMessages, updateSessionName, updateSessionHeader, createSession, getActiveId, getComposerGeneration, markActive, saveDraft, clearDraft, consumeDraft, getDraftSnapshot,
} from './sessions.js';
import { getSelected, getCurrentEndpoint, getSelectionSource, isImageSelected, getImageSlot } from './models.js?v=217';
import { openArtifact, extractArtifacts, stripArtifacts } from './artifacts.js';
import { getAttachments, hasPendingAttachments, clearAttachments } from './uploads.js?v=254';
import { isIncognitoMode, getPermMode, getEffort, getReasoningMode, getCustomEffort, modelSupport } from './modes.js?v=259';
import { applyResponsePrivacy, stripEmojis } from './privacy.js';
import { shouldRunInBackground } from './aidebackgroundpolicy.js';
import { formatNumber, serverText, t, tp, t as tr } from './i18n.js';
import { contextProvenanceElement, sourceCitationStatus } from './memoryactions.js';
import { saveAnswerNote } from './answer_note.js';
import { fetchWithRecentOwner } from './recent_owner.js';
import { loadProjects } from './projects.js';
import { saveAnswerTask } from './answer_task.js';
import { markAideQuestionResolved, renderAideQuestion } from './aidequestions.js?v=2';
import { compactResponseActions } from './response_actions.js?v=6';
import { addQueued, clearQueued, queuedItems, restoreQueued, takeQueued } from './chatqueue.js';
import { esc as escHtml } from './escape.js';

// one-line human summary of a tool call, so an approval reads clearly, not as raw json
function toolSummary(name, args = {}) {
  const a = args || {};
  const cut = (s, n = 70) => String(s || '').replace(/\s+/g, ' ').slice(0, n);
  switch (name) {
    case 'read_file': return t('aide.step_read', { path: a.path || '' });
    case 'write_file': return t('aide.step_write', { path: a.path || '' });
    case 'edit_file': return t('aide.step_edit', { path: a.path || '' });
    case 'apply_patch': return t('aide.step_apply_patch');
    case 'shell': case 'bash': return t('aide.step_run', { command: cut(a.command, 90) });
    case 'grep_files': return t('aide.step_grep', { pattern: cut(a.pattern, 40) });
    case 'glob_files': return t('aide.step_glob', { pattern: a.pattern || '' });
    case 'list_files': return t('aide.step_list', { path: a.path || '.' });
    case 'web_search': return t('aide.step_search', { query: cut(a.query, 50) });
    case 'web_fetch': return t('aide.step_fetch', { url: cut(a.url, 60) });
    case 'pi_run': return t('aide.step_hand_to_pi', { task: cut(a.task, 110) });
    case 'git_commit': return t('aide.step_git_commit');
    case 'git_status': return t('aide.step_git_status');
    case 'git_diff': return t('aide.step_git_diff');
    case 'todo_update': return t('aide.step_todo_update');
    case 'memory_search': return t('aide.step_recall', { query: cut(a.query, 40) });
    case 'memory_add': return t('aide.step_remember');
    case 'diagnostics': return t('aide.step_diagnostics');
    case 'mail_send': return t('aide.step_send_mail', { to: cut(a.to, 40) });
    case 'project_create': return t('aide.step_project_create', { path: cut(a.path, 90) });
    default: {
      const v = Object.values(a).find(x => typeof x === 'string' && x.length < 80);
      return v ? `${name}: ${cut(v)}` : name;
    }
  }
}

// expose mdToHtml for sessions.js lazy fallback
window._mdToHtml = mdToHtml;

// copy button for ai messages — global
window.copyMsg = function(btn) {
  const body = btn.closest('.ai-wrap').querySelector('.ai-content');
  writeClipboard(body?.innerText || '').then(() => {
    btn.textContent = t('common.copied');
    setTimeout(() => btn.textContent = t('common.copy'), 1500);
  });
};

// save an assistant message as a note or task
window.saveMsgAs = async function(btn, kind) {
  if (kind === 'note') return saveAnswerNote(btn);
  if (kind === 'task') return saveAnswerTask(btn);
};

// open artifact from msg actions row
window.openArtifactFromMsg = function(btn) {
  const wrap = btn.closest('.ai-wrap');
  const raw = wrap?.dataset.artifacts;
  if (!raw) return;
  const [a] = JSON.parse(raw);
  if (a) openArtifact(a.content, a.type, a.title, a.lang);
};

// message actions and step toggles are drawn as html here and in sessions.js. the csp blocks
// inline onclick, so one listener runs them all
if (typeof document !== 'undefined') document.addEventListener?.('click', e => {
  const toggle = e.target.closest?.('[data-toggle-open]');
  if (toggle) { toggle.parentElement.classList.toggle('open'); return; }
  const btn = e.target.closest?.('[data-msg-act]');
  if (!btn || btn.disabled) return;
  const act = btn.dataset.msgAct;
  if (act === 'copy') window.copyMsg(btn);
  else if (act === 'note' || act === 'task') window.saveMsgAs(btn, act);
  else if (act === 'artifact') window.openArtifactFromMsg(btn);
  else if (act === 'steps') openReplySteps(btn);
  else if (act === 'remember') window.rememberUserMessage?.(btn);
});

let _streaming = false;
// the task the running reply belongs to, until its stream has fully ended (a stop clears
// _chatSessionId earlier)
let _streamingSession = null;
let _backgroundLaunching = false;
let _chatAbort = null;
let _chatSessionId = null;
// the row the running reply streams into; switching tasks away and back redraws the list without it
let _chatStreamRow = null;
// the running turn's token: the stop button names it, so a late stop can't end the next turn
let _chatTurnToken = '';
// turns the owner stopped here; their stream may still end on its own a moment later
const _stoppedTurns = new Set();
// the running stream's end, and what its row shows while it stops
let _chatStreamDone = null;
let _chatStopping = null;
let _streamToken = 0;

export function getSendBlockReason() {
  if (_streaming || _backgroundLaunching) return 'busy';
  return window._aidePrimaryUnavailable ? 'primary-unavailable' : '';
}

export function canSendMessage() {
  return !getSendBlockReason();
}

// while aide replies in this task, a new message waits its turn instead of being refused
export function canQueueMessage() {
  return _streaming && !_backgroundLaunching && !window._aidePrimaryUnavailable
    && !!_streamingSession && getActiveId() === _streamingSession;
}

// one at a time, in the order they were sent
let _queueTail = Promise.resolve();
let _queueFiles = false;
async function queueMessage(text, onAccepted) {
  if (_queueFiles) return;
  const sessionId = getActiveId();
  if (hasPendingAttachments()) { showSendIssue(t('aide.send_wait_attachments')); return; }
  // notes, other apps' context and pictures are sent one at a time, as before
  if (window._pendingDocumentScope || isImageSelected() || getImageSlot()) { toast(t('shell.wait_for_answer'), 'error'); return; }
  const attachmentIds = getAttachments();
  const privateTask = isIncognitoMode();
  if (attachmentIds.length) {
    // files stay attached until the server has the message
    _queueFiles = true;
    try {
      if (!await addQueued(sessionId, text, attachmentIds, { privateTask })) return;
    } finally { _queueFiles = false; }
    clearAttachments(attachmentIds);
    onAccepted(sessionId);
    return;
  }
  // the box empties at once, so a quick second Enter can't send the same words again; if the
  // server never took them they go back into the box
  onAccepted(sessionId);
  const job = _queueTail.then(() => addQueued(sessionId, text, [], { privateTask }));
  _queueTail = job.catch(() => {});
  if (!await job && getActiveId() === sessionId) restoreComposerInput(text);
}

// the reply ended: what came in meanwhile is answered next, all together
let _flushing = false;
export async function answerQueued(sessionId = getActiveId()) {
  if (_flushing || !sessionId || getActiveId() !== sessionId) return;
  _flushing = true;
  try {
    // the server lets go of the finished turn a moment after the stream closes
    for (let waited = 0; ; waited += 150) {
      if (_streaming || getActiveId() !== sessionId || !queuedItems(sessionId).length) return;
      const state = await fetch(`/api/chat/queue/${encodeURIComponent(sessionId)}`).then(r => r.ok ? r.json() : null).catch(() => null);
      if (!state || !state.answering || waited >= 15000) break;
      await new Promise(resolve => setTimeout(resolve, 150));
    }
    const sel = getSelected();
    const taken = takeQueued(sessionId);
    if (!taken || !sel || _streaming || !canSendMessage()) return;
    const userRow = taken.askRow();
    showMessages();
    // not awaited: the guard covers only the start, so messages sent during this turn flush after it
    void streamReply({
      session_id: sessionId,
      message: taken.text,
      mode: getMode(),
      file_ids: taken.fileIds,
      incognito: isIncognitoMode(),
      permission_mode: getPermMode(),
      effort: getEffort(sel.model, modelSupport(sel).effortLevels),
      reasoning_mode: getReasoningMode(sel.model, modelSupport(sel).reasoningControl),
      custom_effort: getCustomEffort(sel.model),
      queued_ids: taken.ids,
    }, { userRow, taken });
  } finally { _flushing = false; }
}

// a run this tab is streaming into a row still on screen is the reply, not background work to
// reattach to. once the owner leaves the task and comes back, that row is gone and the card shows it
window._aideStreamsHere = sessionId => _streaming && _chatSessionId === sessionId && !!_chatStreamRow?.isConnected;

function normalizeDocumentScope(value) {
  if (!value) return null;
  if (value.kind === 'vault_documents') {
    if (!Array.isArray(value.documents) || !value.documents.length || value.documents.length > 8) return null;
    const documents = value.documents.map(item => ({ path: String(item.path || ''), expected_hash: String(item.expected_hash || '') }));
    if (documents.some(item => !item.path || !item.expected_hash)) return null;
    return { kind: 'vault_documents', documents };
  }
  if (value.kind !== 'vault_document') return null;
  const path = String(value.path || '').trim();
  const expectedHash = String(value.expected_hash || '').trim();
  return path && expectedHash ? { kind: 'vault_document', path, expected_hash: expectedHash } : null;
}

function renderDocumentScope(scope) {
  const chip = document.getElementById('aide-document-scope');
  if (!chip) return;
  chip.hidden = !scope;
  const name = document.getElementById('aide-document-scope-name');
  if (name) name.tabIndex = scope ? 0 : -1;
  if (name) name.textContent = scope?.kind === 'vault_documents' ? tp('aide.scope_notes', scope.documents.length, { paths: scope.documents.map(item => item.path).join(', ') }) : scope ? scope.path.split('/').pop().replace(/\.(md|markdown)$/i, '') : '';
}

window._setAideDocumentScope = scope => {
  window._pendingDocumentScope = normalizeDocumentScope(scope);
  renderDocumentScope(window._pendingDocumentScope);
  saveDraft();
};
document.getElementById('aide-document-scope-remove')?.addEventListener('click', () => {
  window._setAideDocumentScope(null);
});

function restoreComposerInput(text) {
  const composer = document.getElementById('composer-ta');
  if (!composer) return;
  const current = composer.value.trim();
  composer.value = current && current !== text.trim() ? `${text}\n\n${composer.value}` : text;
  composer.style.height = 'auto';
  composer.dispatchEvent(new Event('input', { bubbles: true }));
  composer.focus();
}

// a send refused before it started (409 turn_in_progress). its words went back into the
// composer, so the retry or a fresh send takes them out again instead of doubling them
let _refusedTurn = null;

function noteRefusedTurn(sessionId, message, row, previousRow) {
  if (previousRow) {
    if (_refusedTurn?.row === previousRow) _refusedTurn.row = row;
    return;
  }
  const before = row.previousElementSibling;
  _refusedTurn = { sessionId, message, row, userRow: before?.querySelector('.user-bubble') ? before : null };
}

// the retry went through, so the copy put back in the composer has been sent
function refusedRetryAccepted(sessionId, previousRow) {
  if (!previousRow || _refusedTurn?.row !== previousRow) return;
  const { message } = _refusedTurn;
  _refusedTurn = null;
  const composer = document.getElementById('composer-ta');
  if (!composer || getActiveId() !== sessionId) return;
  const value = composer.value;
  // restoreComposerInput puts it in front of whatever was already typed
  const next = value.trim() === message.trim() ? '' : value.startsWith(`${message}\n\n`) ? value.slice(message.length + 2) : value;
  if (next === value) return;
  composer.value = next;
  composer.style.height = 'auto';
  composer.dispatchEvent(new Event('input', { bubbles: true }));
}

// sending again from the composer replaces the refused rows, it doesn't stack a second bubble
function dropRefusedTurn(sessionId) {
  const turn = _refusedTurn;
  _refusedTurn = null;
  if (turn?.sessionId !== sessionId) return;
  turn.userRow?.remove();
  turn.row.remove();
}

function restoreBackgroundInput(sessionId, text) {
  // A delayed enqueue failure still belongs to the conversation that sent it.
  if (getActiveId() === sessionId && !isIncognitoMode()) {
    restoreComposerInput(text);
    return;
  }
  const draft = getDraftSnapshot(sessionId);
  if (!draft || typeof draft.text !== 'string') {
    toast(t('aide.background_restore_failed'), 'error');
    return;
  }
  const restored = draft.text.trim() && draft.text.trim() !== text.trim()
    ? `${text}\n\n${draft.text}` : text;
  if (!consumeDraft(sessionId, draft, restored, draft.document_scope || null)) {
    toast(t('aide.background_restore_failed'), 'error');
  }
}

function restoreDocumentScope(scope) {
  if (!scope || scope.kind === 'handoff') return;
  window._setAideDocumentScope(scope);
}


async function offerTaskAdd(text) {
  const button = document.getElementById('composer-send-task');
  const message = String(text || '').trim();
  if (!button || !message) return;
  const ask = preview => fetch('/api/tasks/quick', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text: message, preview, from_message: true }),
  });
  try {
    const checked = await ask(true);
    const read = await checked.json().catch(() => ({}));
    // the words moved on while it was checked: the offer would be for something else
    if (!checked.ok || !read.understood || document.getElementById('composer-ta')?.value.trim() !== message) return;
    button.hidden = false;
    button.onclick = async () => {
      button.disabled = true;
      try {
        const added = await ask(false);
        const task = await added.json().catch(() => ({}));
        if (!added.ok) throw new Error(task.detail || '');
        toast(t('aide.send_task_added', { title: task.title }), 'success');
        button.hidden = true;
      } catch {
        toast(t('aide.send_task_add_failed'), 'error');
      } finally {
        button.disabled = false;
      }
    };
  } catch { /* choosing a model is still on offer */ }
}

function showSendIssue(message, chooseModel = false) {
  const recovery = document.getElementById('composer-send-recovery');
  if (!recovery) { toast(message, 'error'); return; }
  recovery.hidden = false;
  recovery.querySelector('p').textContent = message;
  recovery.querySelector('button').hidden = !chooseModel;
  // no model to answer with: a message that reads as a task can still be kept as one
  const addTask = document.getElementById('composer-send-task');
  if (addTask) addTask.hidden = true;
  if (chooseModel) void offerTaskAdd(document.getElementById('composer-ta')?.value);
  const composer = document.getElementById('composer-ta');
  if (composer?.getClientRects().length && ['composer-ta', 'send-btn'].includes(document.activeElement?.id)) composer.focus();
}

// Keep a scoped question recoverable until the server accepts the turn. The
// same ownership check is used by the original send and a refused-turn retry.
function holdDocumentDraft(sessionId, draft, attachmentIds, privateReply, { ownsText = true, submittedRecord = draft, retiredDraft = null } = {}) {
  const composer = document.getElementById('composer-ta');
  let accepted = false, consumed = false, generation = null;
  return {
    accept() {
      if (accepted) return;
      accepted = true;
      const sameAttachments = !hasPendingAttachments() && JSON.stringify(getAttachments()) === JSON.stringify(attachmentIds);
      clearAttachments(attachmentIds);
      if (retiredDraft && !privateReply) consumeDraft(null, retiredDraft, ownsText ? '' : draft.text);
      if (!privateReply) consumeDraft(sessionId, submittedRecord, ownsText ? '' : draft.text);
      if (getActiveId() !== sessionId || isIncognitoMode() !== privateReply) return;
      if (!composer || composer.value !== draft.text
        || JSON.stringify(normalizeDocumentScope(window._pendingDocumentScope)) !== JSON.stringify(draft.document_scope)
        || !sameAttachments) return;
      consumed = true;
      generation = getComposerGeneration();
      if (ownsText) composer.value = '';
      composer.style.height = 'auto';
      window._setAideDocumentScope(null);
      composer.dispatchEvent(new Event('input', { bubbles: true }));
    },
    restore(answer) {
      if (!consumed || getActiveId() !== sessionId || getComposerGeneration() !== generation
        || isIncognitoMode() !== privateReply || composer.value !== (ownsText ? '' : draft.text) || window._pendingDocumentScope
        || hasPendingAttachments() || getAttachments().length) return;
      restoreDocumentScope(draft.document_scope);
      if (ownsText && !answer) restoreComposerInput(draft.text);
    },
  };
}

// what another app hands over with a question (andromeda's results, the ask panel's screen): the
// model reads it, the owner's message shows only the question and where it came from
function normalizeHandoff(value) {
  if (value?.kind !== 'handoff') return null;
  const app = String(value.app || '').trim().slice(0, 64);
  const context = String(value.context || '');
  if (!app || !context.trim()) return null;
  const sources = (Array.isArray(value.sources) ? value.sources : [])
    .map(item => ({ title: String(item?.title || '').slice(0, 500), url: String(item?.url || '') }))
    .filter(item => /^https?:\/\//i.test(item.url) && item.url.length <= 2048)
    .slice(0, 20);
  const note = normalizeDocumentScope(value.note && { kind: 'vault_document', ...value.note });
  return { kind: 'handoff', app, context, sources, ...(note ? { note: { path: note.path, expected_hash: note.expected_hash } } : {}) };
}

// a handoff whose send was refused before it started (no model picked yet, a file still
// uploading) waits with its question: the composer keeps only the question, so the send that
// follows still carries the other app's context instead of the bare words
let _heldHandoff = null;

function takeHandoff(text, handoff) {
  if (handoff) _heldHandoff = { handoff, question: text.trim() };
  else if (_heldHandoff && !text.includes(_heldHandoff.question)) _heldHandoff = null;
  return _heldHandoff?.handoff || null;
}

export async function sendMessage(text, onAccepted = () => {}, { handoff = null } = {}) {
  if (text?.trim() && !handoff && canQueueMessage()) return queueMessage(text, onAccepted);
  if (!text?.trim() || _streaming || _backgroundLaunching) return;
  handoff = takeHandoff(text, normalizeHandoff(handoff));
  if (window._aidePrimaryUnavailable) {
    showSendIssue(t('aide.send_reopen_main'));
    return;
  }
  if (hasPendingAttachments()) {
    showSendIssue(t('aide.send_wait_attachments'));
    return;
  }

  let attachmentIds = getAttachments();
  let documentScope = normalizeDocumentScope(window._pendingDocumentScope);
  const privateReply = isIncognitoMode();
  let draft = { text: document.getElementById('composer-ta')?.value || '', document_scope: documentScope };
  let sessionId = getActiveId();
  let originalRecord = documentScope && !privateReply ? getDraftSnapshot(sessionId) : null;
  let freshSession = false;

  // no active session — create one lazily now (first message)
  if (!sessionId) {
    const composerGeneration = getComposerGeneration();
    const ep = getCurrentEndpoint();
    if (!ep) { showSendIssue(t('aide.send_choose_model'), true); return; }
    const model = getSelected()?.model || ep.models[0] || '';
    let s;
    try {
      s = await createSession(model, ep.id, {
        incognito: isIncognitoMode(),
        mode: 'agent',
        chatBehavior: window._pendingChatBehavior || '',
      });
    } catch { /* The composer still owns the unsent text. */ }
    if (!s) {
      if (getComposerGeneration() === composerGeneration) showSendIssue(t('aide.send_task_failed'));
      return;
    }
    if (getComposerGeneration() !== composerGeneration) return;
    // carry over a persona picked before the session existed (fresh-chat picker)
    if (window._pendingPersona) {
      try {
        await fetch(`/api/sessions/${s.id}`, {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ persona_id: window._pendingPersona }),
        });
        s.persona_id = window._pendingPersona;
      } catch {}
      window._pendingPersona = null;
    }
    if (getComposerGeneration() !== composerGeneration) return;
    window._currentSession = s;
    sessionId = s.id;
    freshSession = true;     // first message ever → auto-name it after the reply
    markActive(sessionId);   // highlight + set active, don't re-render
  }

  const sel = getSelected();
  if (!sel) { showSendIssue(t('aide.send_choose_model'), true); return; }
  if (!documentScope) {
    // Ordinary sends keep input added during creation, including a first source choice.
    attachmentIds = getAttachments();
    documentScope = normalizeDocumentScope(window._pendingDocumentScope);
    if (documentScope) {
      draft = { text: document.getElementById('composer-ta')?.value || '', document_scope: documentScope };
      originalRecord = !privateReply ? getDraftSnapshot(freshSession ? null : sessionId) : null;
    }
  }
  if (documentScope?.kind === 'vault_documents' && attachmentIds.length) {
    showSendIssue(t('aide.send_remove_attachments'));
    return;
  }

  document.getElementById('composer-send-recovery')?.setAttribute('hidden', '');
  // Adopt the new task's draft before awaiting the request, including edits made
  // during task creation. At quota, keep the old copy instead of deleting it.
  const savedDraft = documentScope && !privateReply && saveDraft();
  if (freshSession && savedDraft) clearDraft(null);
  // Only a failed write can leave the submitted question's old scope in storage.
  // A successfully adopted newer scope is never owned by this request.
  const submittedRecord = { ...draft, text: draft.text.trim() ? draft.text : '' };
  const quotaRecord = !savedDraft && originalRecord?.text === submittedRecord.text ? originalRecord : null;
  const pendingDraft = documentScope ? holdDocumentDraft(sessionId, draft, attachmentIds, privateReply, {
    ownsText: draft.text.trim() === text.trim(),
    submittedRecord: !freshSession && quotaRecord ? quotaRecord : submittedRecord,
    retiredDraft: freshSession ? quotaRecord : null,
  }) : null;
  if (!documentScope) onAccepted(sessionId);
  dropRefusedTurn(sessionId);
  _heldHandoff = null;

  // image model picked as the primary → generate (legacy single-pick path)
  if (!documentScope && !handoff && isImageSelected()) { _sendImage(text, sessionId, freshSession, getSelected()); return; }
  // companion image slot set + the message reads like an image request → route to it
  const imgSlot = getImageSlot();
  if (!documentScope && !handoff && imgSlot && _looksLikeImageRequest(text)) { _sendImage(text, sessionId, freshSession, imgSlot); return; }

  if (!documentScope && !handoff && shouldRunInBackground(text) && !isIncognitoMode()) {
    _backgroundLaunching = true;
    showMessages();
    const userRow = appendUserMsg(text);
    scrollDown();
    let run = null;
    try {
      const { startBackgroundWork } = await import('./aidebackground.js?v=248');
      run = await startBackgroundWork({
        sessionId,
        request: text,
        fileIds: attachmentIds,
        selection: sel,
        selectionSource: getSelectionSource(),
        permissionMode: getPermMode(),
        effort: getEffort(sel?.model, modelSupport(sel).effortLevels),
        reasoningMode: getReasoningMode(sel?.model, modelSupport(sel).reasoningControl),
        customEffort: getCustomEffort(sel?.model),
      });
    } catch (error) {
      toast(error?.message || t('aide.bg_start_failed'), 'error');
    } finally {
      _backgroundLaunching = false;
    }
    if (!run) {
      userRow.remove();
      restoreBackgroundInput(sessionId, text);
      return;
    }
    if (getActiveId() === sessionId) clearAttachments(attachmentIds);
    if (freshSession) updateSessionName(sessionId, text.slice(0, 54));
    return;
  }

  showMessages();
  const userRow = appendUserMsg(text, documentScope || handoff);
  if (!documentScope) {
    window._setAideDocumentScope(null);
    clearAttachments();
  }
  scrollDown();

  return streamReply({
    session_id: sessionId,
    message: text,
    mode: getMode(),
    file_ids: [...attachmentIds],
    incognito: privateReply,
    permission_mode: getPermMode(),
    effort: getEffort(sel.model, modelSupport(sel).effortLevels),
    reasoning_mode: getReasoningMode(sel.model, modelSupport(sel).reasoningControl),
    custom_effort: getCustomEffort(sel.model),
    context_scope: documentScope || handoff || undefined,
  }, { freshSession, pendingDraft, userRow });
}

// edit and regenerate ask the server to answer a stored question again. it checks this tab saw
// the newest turn and the question's notes and files are still there, then answers in one go.
// resolves 'accepted' once it took the request; otherwise why not (nothing changed): 'stale'
// (another tab moved the task on), 'gone' (the question was removed), 'offline', or 'refused'
export function resendMessage(userRow, text, { edit = false, newestId = '', onAccepted = () => {} } = {}) {
  const sessionId = getActiveId();
  const messageId = userRow?.dataset.msgId;
  if (!sessionId || !messageId || !text?.trim() || !canSendMessage()) return Promise.resolve('refused');
  const sel = getSelected();
  if (!sel) { showSendIssue(t('aide.send_choose_model'), true); return Promise.resolve('refused'); }
  showMessages();
  return new Promise(resolve => {
    void streamReply({
      session_id: sessionId,
      message: text,
      mode: getMode(),
      // the server uses the notes and files the question was stored with, never the tab's
      file_ids: [],
      incognito: isIncognitoMode(),
      permission_mode: getPermMode(),
      effort: getEffort(sel.model, modelSupport(sel).effortLevels),
      reasoning_mode: getReasoningMode(sel.model, modelSupport(sel).reasoningControl),
      custom_effort: getCustomEffort(sel.model),
      [edit ? 'edit_message_id' : 'regenerate_message_id']: messageId,
      newest_id: newestId,
    }, {
      userRow,
      shownScope: userRow.contextScope || null,
      resend: {
        // a regenerate keeps the answer it replaces until the new one has words
        keepOld: !edit,
        accepted: row => { onAccepted(row); resolve('accepted'); },
        refused: (reason, turn) => resolve(reason === 'stopped' ? { reason, turn } : reason),
      },
    });
  });
}

// why an edit or regenerate was turned down, and plain words for the ones said here (a stale or
// gone question is re-read first, and the edit box says what happened)
function resendRefusal(status, error) {
  if (error.code === 'history_moved') return { reason: 'stale' };
  // the owner's own stop got there first: nothing was cut, the history is just re-read
  if (error.code === 'turn_stopped') return { reason: 'stopped' };
  if (status === 404) return { reason: 'gone' };
  if (error.code === 'recent_auth_required') return { reason: 'refused', words: t('aide.full_access_needs_password') };
  const detail = typeof error.detail === 'string' ? error.detail : error.detail?.message;
  return { reason: 'refused', words: plainError(detail || t('aide.resend_failed')) };
}

export function retrySavedResponse(request, previousRow) {
  if (!canSendMessage() || getActiveId() !== request.session_id || !previousRow?.isConnected) return false;
  void streamReply(request, { previousRow });
  document.getElementById('composer-ta')?.focus();
  return true;
}

// where focus goes when the control it was on goes away with the reply's end. keyboards stay on
// the composer; on touch that would pop the on-screen keyboard over the reply, so the reply
// itself takes focus there
function focusAfterReply(row = document.getElementById('messages')?.lastElementChild) {
  const composer = document.getElementById('composer-ta');
  const coarse = globalThis.matchMedia?.('(pointer: coarse)')?.matches;
  if (coarse && row?.isConnected) {
    if (!row.hasAttribute('tabindex')) row.tabIndex = -1;
    row.focus({ preventScroll: true });
  } else composer?.focus();
}

async function streamReply(request, { freshSession = false, previousRow = null, pendingDraft = null, userRow = null, shownScope = null, resend = null, taken = null } = {}) {
  const { session_id: sessionId, message: text, incognito: privateReply } = request;
  // an edit or regenerate leaves the notes to the server; the row still shows what it used
  const documentScope = request.context_scope || shownScope;
  // Only the latest settled failure may retry. A new turn retires older controls.
  document.querySelectorAll('.aide-retry-response').forEach(button => button.remove());
  previousRow?.remove();
  _streamingSession = sessionId;
  setStreaming(true);
  const ctrl = new AbortController();
  const streamToken = ++_streamToken;
  _chatAbort = ctrl;
  _chatSessionId = sessionId;
  const turnToken = _newImageRequestId();
  _chatTurnToken = turnToken;
  let streamEnd;
  _chatStreamDone = new Promise(resolve => { streamEnd = resolve; });
  const userStopped = () => ctrl.signal.aborted || _stoppedTurns.has(turnToken);
  // what the server did with a regenerate's old answer, once it says
  let regenOutcome;

  const { row, body } = createStreamingAiRow();
  _chatStreamRow = row;
  // an edit or regenerate answers in place, right under its question
  if (resend && userRow?.isConnected) userRow.after(row);
  let accepted = false;

  const contentEl = document.createElement('div');
  contentEl.className = 'ai-content';
  body.appendChild(contentEl);
  let provenanceEl = null;
  let sourceCitations = null;
  let sourceReplyId = "";
  // what needs the owner while aide works (a permission, a question), under the words
  let attentionEl = null;
  // why the last step that failed did, for a turn that ends without words to say it
  let failedStep = '';
  // the steps behind the reply, for its menu (never drawn in the chat)
  const steps = new Map();
  let runId = '';
  let accText = '';
  let cursor = null;
  let genStart = 0;     // first answer token time
  let providerError = false;
  // a regenerate's old answer and the turns after it, hidden until the new answer has words
  const replaced = [];
  let streamBroke = false;
  let sourceUserId = request.retry_message_id || '';
  let receivedDone = false;
  let streamEnded = false;
  let toolActivity = false;
  let rejectedBeforeStart = false;
  // full access wants a recent password; the shared prompt asked and it was cancelled or wrong
  let refusedForPassword = false;
  const progressEl = document.createElement('div');
  progressEl.className = 'aide-run-progress';
  progressEl.setAttribute('role', 'status');
  progressEl.setAttribute('aria-live', 'polite');
  progressEl.textContent = t('aide.progress_typing');
  body.appendChild(progressEl);
  // the reply's status line says it's stopping until the stream ends (it may have gone already)
  _chatStopping = () => {
    progressEl.textContent = t('aide.stopping');
    if (!progressEl.isConnected) body.appendChild(progressEl);
  };
  const clearProgress = () => progressEl.remove();

  const attention = () => {
    if (!attentionEl) {
      attentionEl = document.createElement('div');
      attentionEl.className = 'aide-needs-you';
      body.insertBefore(attentionEl, progressEl.isConnected ? progressEl : null);
    }
    return attentionEl;
  };
  // an answered prompt leaves the stream; focus that was on it goes back to the reply
  const dropPrompt = card => {
    const hadFocus = card.contains(document.activeElement);
    card.remove();
    if (attentionEl && !attentionEl.children.length) { attentionEl.remove(); attentionEl = null; }
    if (hadFocus) focusAfterReply(row);
  };

  // the cursor ends the last line of text; after the rendered paragraph it sat alone on a new line
  const addCursor = (target) => {
    cursor = document.createElement('span');
    cursor.className = 'stream-cursor';
    let host = target;
    while (/^(P|H[1-6]|UL|OL|LI|BLOCKQUOTE)$/.test(host.lastElementChild?.tagName || '')) host = host.lastElementChild;
    host.appendChild(cursor);
  };

  // time-throttled render: first token paints instantly, then at most every ~45ms.
  // uses setTimeout (NOT requestAnimationFrame — rAF pauses in background/unfocused
  // tabs, which made streaming look broken). batching avoids re-parsing the whole
  // response on every token (that was O(n²)).
  let renderTimer = 0;
  let lastRenderAt = 0;
  const flushRender = () => {
    renderTimer = 0;
    lastRenderAt = Date.now();
    const displayText = _splitBeforeArtifact(accText);
    if (!displayText) return;
    cursor?.remove();
    contentEl.innerHTML = mdToHtml(stripEmojis(withoutThinking(displayText)));
    applyResponsePrivacy(contentEl);
    cursor?.remove();
    addCursor(contentEl);
    // follows only while the owner is at the end (scrollfollow.js decides from the position)
    scrollDown();
  };
  const scheduleRender = () => {
    if (renderTimer) return;
    const since = Date.now() - lastRenderAt;
    if (since >= 45) flushRender();                       // paint now
    else renderTimer = setTimeout(flushRender, 45 - since); // trailing paint
  };

  try {
    const r = await fetchWithRecentOwner('/api/chat', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ ...request, turn_token: turnToken }),
      signal: ctrl.signal,
    }, { prompt: t('aide.reauth_prompt', { reason: t('aide.reauth_reason_full_access') }) });

    if (!r.ok && resend) {
      // refused before anything was cut: the history stays as it was
      const error = await r.json().catch(() => ({}));
      row.remove();
      const refusal = resendRefusal(r.status, error);
      if (refusal.words) toast(refusal.words, 'error');
      resend.refused(refusal.reason);
      return;
    }
    if (!r.ok && taken) {
      // the turn that was to answer the waiting messages was refused: they wait as before, and
      // when another tab already sent them this one just reads the task again
      const error = await r.json().catch(() => ({}));
      row.remove();
      if (error.code === 'queue_changed') { clearQueued(taken); userRow?.remove(); void rereadActiveSession(sessionId); }
      else restoreQueued(taken, userRow);
      setStreaming(false);
      return;
    }
    if (!r.ok) {
      const error = await r.json().catch(() => ({}));
      if (error.code === 'turn_stopped') {
        // the owner's stop got there before the turn began: nothing was kept, and it ends the
        // way any stop ends, without an error
        if (userRow && !userRow.dataset.msgId) userRow.dataset.unsaved = '1';
        row.dataset.unsaved = '1';
        throw new DOMException('stopped before it started', 'AbortError');
      }
      refusedForPassword = r.status === 403 && error.code === 'recent_auth_required';
      rejectedBeforeStart = refusedForPassword || (r.status === 409 && error.code === 'turn_in_progress');
      // never stored: an edit sends its words as a new message instead of cutting after it
      if (userRow && !userRow.dataset.msgId) userRow.dataset.unsaved = '1';
      row.dataset.unsaved = '1';
      const message = refusedForPassword
        ? t('aide.full_access_needs_password')
        : typeof error.detail === 'string' ? error.detail : error.detail?.message || t('aide.answer_start_failed');
      const chat = document.getElementById('chat');
      const followedReply = chat && chat.scrollHeight - chat.scrollTop - chat.clientHeight < 96;
      body.innerHTML = rejectedBeforeStart
        ? `<div class="error-msg model-error"><p role="status">${escHtml(message)}</p></div>`
        : `<div class="error-msg">${escHtml(message)}</div>`;
      body.classList.add('done');
      if (rejectedBeforeStart && !pendingDraft && getActiveId() === sessionId) noteRefusedTurn(sessionId, request.message, row, previousRow);
      else if (previousRow && _refusedTurn?.row === previousRow) _refusedTurn = null;
      if (rejectedBeforeStart && !pendingDraft && !previousRow && getActiveId() === sessionId) {
        // the words were refused, not sent: put them back so a reload doesn't lose them, and show
        // the work that holds this conversation (and any question it is waiting on) right away
        restoreComposerInput(request.message);
        import('./bgrun.js').then(m => m.reattach(sessionId)).catch(() => {});
      }
      if (!pendingDraft && !rejectedBeforeStart && !previousRow && getActiveId() === sessionId && _streamToken === streamToken) {
        restoreDocumentScope(documentScope);
        if (documentScope) {
          restoreComposerInput(text);
          // Restoring the source list shrinks the message viewport.
          if (followedReply) scrollDown({ force: true });
        }
      }
      setStreaming(false);
      return;
    }

    accepted = true;
    if (taken) clearQueued(taken);
    // the server took the turn: aide has read the question (a retry answers the one above it)
    let asked = userRow?.isConnected ? userRow : row.previousElementSibling;
    while (asked && !asked.querySelector('.user-bubble')) asked = asked.previousElementSibling;
    markRead(asked);
    if (resend?.keepOld && userRow?.isConnected) {
      for (let next = userRow.nextElementSibling; next; next = next.nextElementSibling) {
        if (next === row) continue;
        next.style.display = 'none';
        replaced.push(next);
      }
    }
    resend?.accepted(row);
    pendingDraft?.accept();
    refusedRetryAccepted(sessionId, previousRow);
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    // proxy-buffering detector: if the whole reply lands in one burst after a
    // long wait, something between the browser and the server held the stream
    const tReq = Date.now();
    let tFirstRead = 0, nReads = 0;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      nReads++;
      if (!tFirstRead) tFirstRead = Date.now();
      buf += decoder.decode(value, { stream: true });

      const lines = buf.split('\n');
      buf = lines.pop();  // last incomplete line stays in buffer

      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        const raw = line.slice(5).trim();
        if (raw === '[DONE]') { receivedDone = true; continue; }

        let chunk;
        try { chunk = JSON.parse(raw); } catch { continue; }

        if (Object.keys(chunk).some(key => key.startsWith('tool_') || key.startsWith('user_question') || key === 'todo_update')) toolActivity = true;
        if (chunk.error) {
          providerError = true;
          cursor?.remove();
          // appendChild, not innerHTML += — the latter re-parses all of body and detaches the
          // live prompt cards and their listeners
          appendError(body, chunk.error);
          if (isConnError(chunk.error)) showConnBanner();
          continue;
        }

        if (chunk.done && chunk.usage) {
          const u = chunk.usage;
          // openai uses prompt/completion_tokens; anthropic uses input/output_tokens
          const inp = u.prompt_tokens || u.input_tokens || 0;
          const out = u.completion_tokens || u.output_tokens || 0;
          const total = inp + out;
          if (total) {
            const el = document.getElementById('session-token-count');
            const value = document.getElementById('session-token-count-value');
            if (el && value) {
              const formatted = formatNumber(total);
              value.textContent = t('aide.tokens_short', { count: formatted });
              el.setAttribute('aria-label', t('aide.tokens_used', { count: formatted }));
              el.hidden = false;
            }
          }
        }

        if (chunk.agent_run) runId = chunk.agent_run.id || runId;
        if (chunk.tool_start) steps.set(chunk.tool_start.call_id, { name: chunk.tool_start.name, args: chunk.tool_start.args || {} });
        if (chunk.tool_diff && steps.has(chunk.tool_diff.call_id)) steps.get(chunk.tool_diff.call_id).diff = chunk.tool_diff.diff;
        if (chunk.tool_result && steps.has(chunk.tool_result.call_id)) {
          Object.assign(steps.get(chunk.tool_result.call_id), { output: chunk.tool_result.output, error: !!chunk.tool_result.error });
        }

        if (chunk.regenerated) regenOutcome = chunk.regenerated.replaced;

        if (chunk.turn) {
          // the server names both rows before anything else, so a reply stopped a moment later
          // still knows its question's id and the id its own reply will be kept under
          if (chunk.turn.user_id) {
            sourceUserId = chunk.turn.user_id;
            if (userRow?.isConnected) { userRow.dataset.msgId = chunk.turn.user_id; delete userRow.dataset.unsaved; }
          }
          if (chunk.turn.assistant_id && !row.dataset.msgId) row.dataset.reservedId = chunk.turn.assistant_id;
        }

        if (chunk.saved_user?.id) {
          sourceUserId = chunk.saved_user.id;
          // the question's own row can now be edited, regenerated or branched without a reload
          if (userRow?.isConnected) userRow.dataset.msgId = chunk.saved_user.id;
        }

        if (chunk.saved_message) {
          row.dataset.msgId = chunk.saved_message.id;
          delete row.dataset.reservedId;
          if (typeof chunk.saved_message.content === 'string') accText = chunk.saved_message.content;
          sourceCitations = chunk.saved_message.source_citations;
        }

        if (chunk.context_provenance) {
          sourceReplyId = chunk.context_provenance.reply_id || "";
          // it joins the reply's actions row when the reply ends, never the stream before that
          provenanceEl?.remove();
          provenanceEl = contextProvenanceElement(chunk.context_provenance);
        }

        // the chat is the reply and nothing else (owner, nov 2: "nothing but a reply, a read,
        // and a typing"). steps, plans, thinking and tool output stay in the run's record; only a
        // permission or a question shows, under the words, until it's answered
        if (chunk.tool_permission) {
          const t = chunk.tool_permission;
          const card = document.createElement('div');
          card.className = `agent-perm${t.diff ? ' has-diff' : ''}`;
          card.dataset.req = t.request_id;
          card.dataset.callId = t.call_id || '';
          card.innerHTML = `
            <div class="agent-perm-msg">${escHtml(tr('aide.perm_approve_prompt', { summary: '\u0001' })).replace('\u0001', `<b>${escHtml(toolSummary(t.name, t.args))}</b>`)}${t.outside
              ? `<span class="agent-perm-outside">${escHtml(t.outside)}</span>`
              : ''}</div>
            ${t.diff ? `<pre class="agent-perm-diff" tabindex="0" aria-label="${escHtml(toolSummary(t.name, t.args))}">${renderDiff(t.diff)}</pre>` : ''}
            <div class="agent-perm-actions">
              <button class="agent-perm-allow">${escHtml(tr('aide.perm_allow'))}</button>
              <button class="agent-perm-deny">${escHtml(tr('aide.perm_deny'))}</button>
            </div>`;
          attention().appendChild(card);
          const decide = async (allow) => {
            card.querySelectorAll('button').forEach(b => b.disabled = true);
            const sent = await fetchWithRecentOwner(`/api/agent/permission/${t.request_id}`, {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ allow }),
            }).catch(() => null);
            if (!sent?.ok) {
              // the server did not take the answer: the card must not say it did
              card.querySelectorAll('button').forEach(b => { b.disabled = false; });
              toast(tr('common.request_failed'), 'error');
              return;
            }
            dropPrompt(card);
          };
          card.querySelector('.agent-perm-allow').addEventListener('click', () => decide(true));
          card.querySelector('.agent-perm-deny').addEventListener('click', () => decide(false));
          scrollDown();
        }

        if (chunk.tool_permission_resolved) {
          // answered elsewhere or timed out
          const id = chunk.tool_permission_resolved.call_id || '';
          const card = [...(attentionEl?.querySelectorAll('.agent-perm') || [])].find(item => item.dataset.callId === id);
          if (card) dropPrompt(card);
        }

        if (chunk.user_question) {
          renderAideQuestion(attention(), chunk.user_question);
          scrollDown();
        }

        if (chunk.user_question_resolved) {
          const resolved = chunk.user_question_resolved;
          markAideQuestionResolved(attentionEl, resolved.id, resolved.answer?.cancelled === true);
        }

        if (chunk.tool_result?.error) {
          // a failed step's reason is the server's own sentence: kept in the reader's language
          failedStep = String(chunk.tool_result.output || '').split('\n').map(serverText).join('\n').trim() || failedStep;
        }

        if (chunk.delta) {
          if (!genStart) { genStart = Date.now(); hideConnBanner(); }  // a real token = we're connected, clear any stale warning
          accText += chunk.delta;
          scheduleRender();
        }
      }
    }

    streamEnded = true;

    // whole reply in one burst after >2.5s of silence = a buffering proxy ate
    // the stream (clash etc. buffer plain-http chunked responses when the
    // *.localhost host isn't in the bypass list). tell the user once a day.
    if (tFirstRead && nReads > 3 && tFirstRead - tReq > 2500 && Date.now() - tFirstRead < 150) {
      const k = 'stream-buffer-warned';
      if (Date.now() - (+localStorage.getItem(k) || 0) > 86400000) {
        localStorage.setItem(k, Date.now());
        toast(t('aide.stream_buffered'), 'error');
      }
    }

  } catch (e) {
    if (taken && !accepted) {
      // no answer: the waiting messages stay where they were, and the server still holds them
      row.remove();
      restoreQueued(taken, userRow);
      return;
    }
    if (resend && !accepted) {
      // no answer from the server: it may or may not have taken it (a stop can land after it
      // did), so the edit box re-reads once the turn is let go
      row.remove();
      resend.refused(e.name === 'AbortError' ? 'stopped' : 'offline', turnToken);
      return;
    }
    streamBroke ||= e.name !== 'AbortError';
    if (getActiveId() === sessionId && _streamToken === streamToken) {
      if (pendingDraft) pendingDraft.restore(accText);
      else if (!previousRow) {
        restoreDocumentScope(documentScope);
        if (documentScope && !accText) restoreComposerInput(text);
      }
    }
    if (e.name !== 'AbortError') {
      appendError(body, t('aide.stream_error', { message: e.message }));
      if (isConnError(e.message)) showConnBanner();
    }
  } finally {
    if (_chatAbort === ctrl) {
      _chatAbort = null;
      _chatSessionId = null;
    }
    if (_chatStreamRow === row) _chatStreamRow = null;
    if (_chatTurnToken === turnToken) _chatTurnToken = '';
    streamEnd();
    if (_streamToken === streamToken) { _streamingSession = null; setStreaming(false); }
    if (renderTimer) { clearTimeout(renderTimer); renderTimer = 0; }
    clearProgress();
    cursor?.remove();
    body.classList.add('done');
    // a reply that finished without being kept (a provider error) has no id to keep. one that
    // was stopped or cut off may have been kept under its promised id: checked by that id later
    if (row.dataset.reservedId && receivedDone && !ctrl.signal.aborted) {
      delete row.dataset.reservedId;
      row.dataset.unsaved = '1';
    }
    if (userStopped()) appendInterruptionNotice(body);
    else if (streamEnded && !receivedDone && !providerError) {
      appendInterruptionNotice(body, t('aide.response_unconfirmed'));
    }

    // answered questions leave with the turn; one still waiting stays, it needs the owner
    attentionEl?.querySelectorAll('.aide-question-card.answered, .aide-question-card.cancelled').forEach(dropPrompt);

    const artifacts = extractArtifacts(accText);
    const cleanText = stripArtifacts(accText);

    // finalize display — strip artifact tags from rendered markdown
    if (cleanText) {
      if (!contentEl) {
        contentEl = document.createElement('div');
        contentEl.className = 'ai-content';
        body.appendChild(contentEl);
      }
      contentEl.innerHTML = mdToHtml(stripEmojis(withoutThinking(cleanText)));
      applyResponsePrivacy(contentEl);
      announceReply(contentEl);
    } else if (failedStep && !providerError && !userStopped()) appendError(body, failedStep);

    // Retry a definite refusal before the turn is accepted, or a finished provider failure.
    // Unknown transport outcomes must not replay work that might already have happened.
    if (rejectedBeforeStart || (sourceUserId && providerError && receivedDone && streamEnded && !userStopped() && !accText && !toolActivity && !(privateReply && request.file_ids.length))) {
      const retry = document.createElement('button');
      retry.type = 'button'; retry.className = 'btn aide-retry-response'; retry.textContent = t('aide.retry_response');
      retry.addEventListener('click', () => {
        if (!canSendMessage() || getActiveId() !== sessionId || _streamToken !== streamToken || !row.isConnected) return;
        // safari doesn't focus a clicked button, so nothing focused counts as the button too
        const a = document.activeElement;
        const restoreFocus = a === retry || !a || a === document.body;
        // an edit or regenerate already cut and kept its question: the retry just answers it
        const { edit_message_id: _edit, regenerate_message_id: _regen, newest_id: _newest, ...asked } = request;
        void streamReply(rejectedBeforeStart ? request : { ...asked, retry_message_id: sourceUserId }, { freshSession, previousRow: row, pendingDraft: rejectedBeforeStart ? pendingDraft : null, userRow, shownScope });
        if (restoreFocus) focusAfterReply();
      });
      body.querySelector('.error-msg')?.appendChild(retry);
      if (rejectedBeforeStart && !refusedForPassword) {
        // retry can't win while that work waits on you, so offer the way out too
        const stop = document.createElement('button');
        stop.type = 'button'; stop.className = 'btn aide-retry-response'; stop.textContent = t('aide.stop_that_work');
        stop.addEventListener('click', async () => {
          stop.disabled = true;
          await fetch(`/api/chat/stop/${encodeURIComponent(sessionId)}`, { method: 'POST' }).catch(() => {});
          stop.textContent = t('aide.stopped');
          retry.focus();
        });
        body.querySelector('.error-msg')?.appendChild(stop);
        scrollDown({ force: true });
      }
    }

    if (provenanceEl) body.appendChild(provenanceEl);

    // action buttons
    const wrap = body.parentElement;
    if (wrap) {
      wrap.answerText = cleanText;
      wrap.sourceReplyId = sourceReplyId;
      wrap.pendingSourceReply = documentScope?.kind === 'vault_documents' && !sourceCitations;
      wrap.dataset.sessionId = sessionId;
      wrap.dataset.private = String(privateReply);
    }
    if (documentScope?.kind === 'vault_documents' && cleanText) {
      const status = sourceCitationStatus(sourceCitations || { status: 'needs_review' });
      if (status) body.appendChild(status);
    }
    // a reply that used tools and wrote no words still gets its row, so its steps are one tap away
    const hasWords = Boolean(withoutThinking(cleanText));
    if (wrap && (hasWords || artifacts.length || steps.size)) {
      const actions = document.createElement('div');
      actions.className = 'msg-actions';
      let html = '';
      if (hasWords) {
        html += `<button class="act-btn" data-msg-act="copy">${t('common.copy')}</button>`;
        html += `<button class="act-btn" data-msg-act="note">${t('aide.note_button')}</button>`;
        html += `<button class="act-btn" data-msg-act="task">${t('aide.add_plan_task')}</button>`;
        html += `<button class="msg-regen-btn act-btn">${t('aide.regen')}</button>`;
        html += `<button class="msg-rewrite-btn act-btn" data-style="shorter">${t('aide.shorter')}</button>`;
        html += `<button class="msg-rewrite-btn act-btn" data-style="simpler">${t('aide.simpler')}</button>`;
      }
      if (artifacts.length) {
        wrap.dataset.artifacts = JSON.stringify(artifacts);
        html += `<button class="act-btn" data-msg-act="artifact">${t('aide.open_artifact')}</button>`;
      }
      actions.innerHTML = html;
      addStepsAction(actions, [...steps.values()], runId);
      // the same buttons in the same order a reload draws, so regenerate and branch work right away
      if (!privateReply) actions.insertAdjacentHTML('beforeend', `<button class="act-btn msg-branch-btn" aria-description="${t('aide.branch_title')}">${t('aide.branch_button')}</button>`);
      wrap.appendChild(actions);
      compactResponseActions(actions);
      wireMessageActions(row);
      if (hasWords) import('./sessions.js').then(m => m.wireRewriteButtons(actions));
    }

    // auto-open the first artifact
    if (artifacts.length) {
      const a = artifacts[0];
      openArtifact(a.content, a.type, a.title, a.lang);
    }

    scrollDown();

    if (replaced.length) {
      // the server says whether it swapped the answers; the page follows that, never its own
      // guess from the words it saw
      if (regenOutcome === true) replaced.forEach(old => old.remove());
      else if (regenOutcome === false) {
        const hadFocus = row.contains(document.activeElement);
        replaced.forEach(old => { old.style.display = ''; });
        row.remove();
        if (hadFocus) {
          replaced[0].tabIndex = -1;
          replaced[0].focus({ preventScroll: true });
        }
        if (!userStopped()) toast(t('aide.regen_kept_old'), 'error');
      }
    }
    // the stream ended before the server said what it kept (stopped, or the connection broke
    // after it took an edit or regenerate): what it kept is the truth, so read it again
    const unheard = replaced.length && regenOutcome === undefined;
    if (resend && accepted && (unheard || streamBroke || (streamEnded && !receivedDone && !providerError))) {
      // after the turn is saved and let go, not before: a stop can still be finishing
      void rereadActiveSession(sessionId, { afterTurn: turnToken });
    }
    _stoppedTurns.delete(turnToken);

    // aide made a project and moved this chat into it: the header follows without a reload
    if (accepted && [...steps.values()].some(step => step.name === 'project_create' && !step.error)) {
      void followSessionProject(sessionId);
    }

    // name the chat from its first message (async; updates the sidebar when ready)
    if (freshSession && !privateReply && cleanText && row.dataset.msgId) {
      fetch(`/api/sessions/${sessionId}/auto-name`, { method: 'POST' })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d?.name) updateSessionName(sessionId, d.name); })
        .catch(() => {});
    }
    // what came in while this reply ran is answered next, all together
    if (accepted && _streamToken === streamToken) void answerQueued();
  }

}

async function followSessionProject(sessionId) {
  try {
    const [data] = await Promise.all([
      fetch(`/api/sessions/${encodeURIComponent(sessionId)}/history`).then(r => (r.ok ? r.json() : null)),
      loadProjects(),
    ]);
    if (!data?.session || getActiveId() !== sessionId) return;
    window._currentSession = data.session;
    updateSessionHeader(data.session);
  } catch {}
}

function _splitBeforeArtifact(text) {
  const idx = text.indexOf('<aide-artifact');
  return idx === -1 ? text : text.slice(0, idx).trimEnd();
}

// append an error line without nuking the live message DOM (textContent = no escaping needed)
function appendError(body, msg) {
  const el = document.createElement('div');
  el.className = 'error-msg';
  const detail = String(msg || t('aide.model_error_default'));
  const status = Number(detail.match(/HTTP\s+(\d{3})/i)?.[1]);
  const connectionFailure = isConnError(detail);
  if (status || connectionFailure) {
    el.classList.add('model-error');
    const explanation = document.createElement('p');
    explanation.setAttribute('role', 'status');
    explanation.textContent = connectionFailure
      ? t('aide.model_unreachable')
      : status === 404
      ? t('aide.model_not_found')
      : [401, 403].includes(status)
      ? t('aide.model_unauthorized')
      : status === 429
      ? t('aide.model_busy')
      : status >= 500
      ? t('aide.model_unavailable')
      : t('aide.model_cannot_answer');
    const settings = document.createElement('button');
    settings.type = 'button'; settings.className = 'btn'; settings.textContent = t('aide.model_settings');
    settings.addEventListener('click', () => window._openSettings?.('models'));
    const details = document.createElement('details');
    const summary = document.createElement('summary'); summary.textContent = t('aide.error_details');
    const raw = document.createElement('pre'); raw.textContent = detail;
    details.append(summary, raw);
    el.append(explanation, settings, details);
  } else el.textContent = detail;
  body.appendChild(el);
}

// connect-type failures (vs a real HTTP error from the provider) → worth the banner
function isConnError(msg = '') {
  return /can'?t connect|connect\s?error|connection (refused|error|reset|timed ?out|aborted)|failed to (establish|connect)|ECONNREFUSED|ENOTFOUND|getaddrinfo|name resolution|cooling down|network is unreachable|read ?timed ?out/i.test(String(msg));
}

function showConnBanner() {
  const b = document.getElementById('conn-banner');
  const m = document.getElementById('conn-banner-msg');
  if (!b || !m) return;
  m.textContent = t('aide.conn_unavailable');
  b.style.display = 'flex';
}

export function hideConnBanner() {
  const b = document.getElementById('conn-banner');
  if (b) b.style.display = 'none';
}

// a reader hears a reply once, when it's done. #messages itself can't be live: every streamed
// word would be read out as it arrived
function announceReply(content) {
  const region = document.getElementById?.('aide-reply-announce');
  const text = content?.textContent?.trim();
  if (!region || !text) return;
  region.textContent = text.length > 400 ? `${text.slice(0, 400)}…` : text;
}

function setStreaming(val, stoppable = true) {
  _streaming = val;
  // send stays on while a reply runs: a message sent now waits for its turn
  document.getElementById('send-btn').disabled = val && !canQueueMessage();
  const stop = document.getElementById('stop-btn');
  // a new turn, or the end of one, ends any "stopping…"
  stop.removeAttribute?.('aria-disabled');
  stop.setAttribute?.('aria-label', t('common.stop'));
  const stopHadFocus = stop.contains(document.activeElement);
  stop.classList.toggle('visible', val && stoppable);
  // the composer's moving light while Aide works
  document.body?.classList?.toggle('aide-working', !!val);
  // stop hides when the reply ends: focus moves on instead of dropping to the page
  if (stopHadFocus && !stop.classList.contains('visible')) focusAfterReply();
}


export function stopStream() {
  const sid = _chatSessionId;
  const token = _chatTurnToken;
  const ctrl = _chatAbort;
  const streamDone = _chatStreamDone;
  const unfocused = !document.activeElement || document.activeElement === document.body;
  _chatAbort = null;
  _chatSessionId = null;
  _chatTurnToken = '';
  if (!ctrl) {
    setStreaming(false);
    if (unfocused) focusAfterReply();
    return;
  }
  if (token) _stoppedTurns.add(token);
  // the old stream keeps the composer until it ends (at most 800ms): send stays off, the words
  // stay in the box, and the stop control says it's stopping
  const stop = document.getElementById('stop-btn');
  stop.setAttribute('aria-disabled', 'true');
  stop.setAttribute('aria-label', t('aide.stopping'));
  _chatStopping?.();
  if (unfocused) focusAfterReply();
  if (!sid) { ctrl.abort(); return; }
  // tell the server first, naming this turn. when it says it stopped this turn, keep reading so
  // its last word (what it kept) arrives; otherwise, or after 800ms, drop the connection. a stop
  // it hears before the connection goes counts as the owner's, and a late one ends nothing
  const told = fetch(`/api/chat/stop/${encodeURIComponent(sid)}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ turn_token: token }),
  }).then(r => r.json()).catch(() => null);
  const deadline = new Promise(resolve => setTimeout(resolve, 800));
  Promise.race([told.then(reply => (reply?.ok ? streamDone : undefined)), deadline]).then(() => ctrl.abort());
}


// rough "is the user asking for a picture" check — only used to auto-route a chat turn to the
// companion image slot. conservative on purpose: an explicit /image|/draw lead-in, or a
// generation verb paired with a visual noun. plain chat must NOT trip it.
function _looksLikeImageRequest(t) {
  const s = String(t).toLowerCase().trim();
  if (/^\/(image|img|draw|gen)\b/.test(s)) return true;
  if (/^(draw|sketch|paint|render|imagine)\b/.test(s)) return true;
  return /\b(draw|generate|create|make|render|paint|design|produce)\b[^.!?]*\b(image|picture|pic|photo|drawing|art|artwork|illustration|logo|icon|wallpaper|poster|painting|portrait|render)\b/.test(s);
}

function _newImageRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

// image-gen turn: same chat thread, but hit the image endpoint. backend saves the
// pic to the gallery + a document and persists the turn, so it survives a reload.
// `target` is {endpointId, model} — the primary (legacy) or the companion image slot.
async function _sendImage(prompt, sessionId, fresh, target) {
  const sel = target || getSelected();
  prompt = prompt.replace(/^\/(image|img|draw|gen)\s+/i, '');   // drop the slash lead-in if any
  const request = { session_id: sessionId, prompt, model: sel.model, endpoint_id: sel.endpointId,
    request_id: _newImageRequestId() };
  showMessages();
  const userRow = appendUserMsg(prompt);
  clearAttachments();
  scrollDown();
  const { row, body } = createStreamingAiRow();
  let error, retry;
  const send = async (again = false) => {
    setStreaming(true, false);
    if (again) {
      retry.setAttribute('aria-disabled', 'true');
      retry.textContent = t('aide.image_retrying');
      error.setAttribute('role', 'status');
      error.textContent = t('aide.image_checking');
    } else {
      const status = document.createElement('div');
      status.className = 'ai-content img-gen-status';
      status.setAttribute('role', 'status');
      status.textContent = t('aide.image_generating');
      body.replaceChildren(status);
    }
    scrollDown();
    try {
      const r = await fetch('/api/images/chat', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify(request),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || t('aide.image_failed'));
      // the stored rows' ids, so an edit or regenerate after this isn't taken for another tab's
      // turn; a private image is never stored
      if (d.user_message_id && d.message_id) {
        userRow.dataset.msgId = d.user_message_id;
        row.dataset.msgId = d.message_id;
      } else {
        userRow.dataset.unsaved = '1';
        row.dataset.unsaved = '1';
      }
      const content = document.createElement('div');
      content.className = 'ai-content';
      content.innerHTML = mdToHtml(d.content);
      body.replaceChildren(content);
      body.classList.add('done');
      if (again) {
        content.tabIndex = -1;
        content.focus({ preventScroll: true });
      }
      if (fresh && d.doc_id && d.doc_title) updateSessionName(sessionId, d.doc_title);
      toast(d.doc_id ? t('aide.image_saved_notes') : t('aide.image_generated'), 'success');
    } catch (e) {
      if (!error) {
        error = document.createElement('div');
        error.className = 'ai-content';
        const template = document.createElement('template');
        template.innerHTML = '<button type="button" class="act-btn img-gen-retry"></button>';
        retry = template.content.firstElementChild;
        retry.addEventListener('click', () => { if (!_streaming) void send(true); });
      }
      error.setAttribute('role', 'alert');
      error.textContent = t('aide.image_unconfirmed', { error: plainError(e.message || t('aide.image_request_failed')) });
      retry.removeAttribute('aria-disabled');
      retry.textContent = t('aide.image_retry');
      if (!again) body.replaceChildren(error, retry);
      toast(e.message || t('aide.image_failed'), 'error');
    } finally {
      setStreaming(false);
      scrollDown();
    }
  };
  await send();
}


function getMode() {
  return 'agent';
}

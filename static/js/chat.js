import { mdToHtml, toast } from './util.js';
import { canRevertTool } from './agentview.js';
import {
  appendUserMsg, appendInterruptionNotice, createStreamingAiRow, scrollDown,
  showMessages, updateSessionName, createSession, getActiveId, getComposerGeneration, markActive, saveDraft, clearDraft, consumeDraft, getDraftSnapshot,
} from './sessions.js';
import { getSelected, getCurrentEndpoint, getSelectionSource, isImageSelected, getImageSlot } from './models.js?v=212';
import { openArtifact, extractArtifacts, stripArtifacts } from './artifacts.js';
import { getAttachments, hasPendingAttachments, clearAttachments } from './uploads.js?v=253';
import { isIncognitoMode, getPermMode, getEffort, getReasoningMode, getCustomEffort } from './modes.js?v=256';
import { applyResponsePrivacy, stripEmojis } from './privacy.js';
import { shouldRunInBackground } from './aidebackgroundpolicy.js';
import { formatNumber, t } from './i18n.js';
import { contextProvenanceElement, sourceCitationStatus } from './memoryactions.js';
import { saveAnswerNote } from './answer_note.js';
import { saveAnswerTask } from './answer_task.js';
import { markAideQuestionResolved, renderAideQuestion } from './aidequestions.js?v=1';

// tools that change state / reach out — flagged in the agent panel + permission cards
const DESTRUCTIVE_TOOLS = new Set(['shell', 'bash', 'write_file', 'edit_file', 'apply_patch',
  'git_commit', 'git_push', 'revert_file', 'delete_file', 'mail_send',
  'computer_click', 'computer_type', 'computer_key', 'computer_scroll']);

// one-line human summary of a tool call (so the panel + approvals read clearly,
// not as raw JSON)
function toolSummary(name, args = {}) {
  const a = args || {};
  const cut = (s, n = 70) => String(s || '').replace(/\s+/g, ' ').slice(0, n);
  switch (name) {
    case 'read_file': return `read ${a.path || ''}`;
    case 'write_file': return `write ${a.path || ''}`;
    case 'edit_file': return `edit ${a.path || ''}`;
    case 'apply_patch': return 'apply a patch';
    case 'shell': case 'bash': return `run: ${cut(a.command, 90)}`;
    case 'grep_files': return `grep "${cut(a.pattern, 40)}"`;
    case 'glob_files': return `glob ${a.pattern || ''}`;
    case 'list_files': return `list ${a.path || '.'}`;
    case 'web_search': return `search: ${cut(a.query, 50)}`;
    case 'web_fetch': return `fetch ${cut(a.url, 60)}`;
    case 'git_commit': return 'git commit';
    case 'git_status': return 'git status';
    case 'git_diff': return 'git diff';
    case 'todo_update': return 'update the checklist';
    case 'memory_search': return `recall: ${cut(a.query, 40)}`;
    case 'memory_add': return 'remember a fact';
    case 'diagnostics': return 'run diagnostics';
    case 'mail_send': return `send mail to ${cut(a.to, 40)}`;
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
  navigator.clipboard.writeText(body?.innerText || '').then(() => {
    btn.textContent = 'copied';
    setTimeout(() => btn.textContent = 'copy', 1500);
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

let _streaming = false;
let _backgroundLaunching = false;
let _chatAbort = null;
let _chatSessionId = null;
let _streamToken = 0;

export function canSendMessage() {
  return !_streaming && !_backgroundLaunching;
}

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
  if (name) name.textContent = scope?.kind === 'vault_documents' ? `${scope.documents.length} note${scope.documents.length === 1 ? '' : 's'} only · ${scope.documents.map(item => item.path).join(', ')}` : scope ? scope.path.split('/').pop().replace(/\.(md|markdown)$/i, '') : '';
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

function restoreDocumentScope(scope) {
  if (!scope) return;
  window._setAideDocumentScope(scope);
}


function showSendIssue(message, chooseModel = false) {
  const recovery = document.getElementById('composer-send-recovery');
  if (!recovery) { toast(message, 'error'); return; }
  recovery.hidden = false;
  recovery.querySelector('p').textContent = message;
  recovery.querySelector('button').hidden = !chooseModel;
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
      if (getActiveId() !== sessionId || isIncognitoMode() !== privateReply) {
        if (!privateReply) consumeDraft(sessionId, submittedRecord, ownsText ? '' : draft.text);
        return;
      }
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

export async function sendMessage(text, onAccepted = () => {}) {
  if (!text?.trim() || _streaming || _backgroundLaunching) return;
  if (hasPendingAttachments()) {
    showSendIssue('wait for attachments to finish uploading.');
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
    if (!ep) { showSendIssue('choose a model before sending.', true); return; }
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
      if (getComposerGeneration() === composerGeneration) showSendIssue('could not start this task. try sending again.');
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
  if (!sel) { showSendIssue('choose a model before sending.', true); return; }
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
    showSendIssue('remove attachments to answer from selected notes only.');
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

  // image model picked as the primary → generate (legacy single-pick path)
  if (!documentScope && isImageSelected()) { _sendImage(text, sessionId, freshSession, getSelected()); return; }
  // companion image slot set + the message reads like an image request → route to it
  const imgSlot = getImageSlot();
  if (!documentScope && imgSlot && _looksLikeImageRequest(text)) { _sendImage(text, sessionId, freshSession, imgSlot); return; }

  if (!documentScope && shouldRunInBackground(text) && !isIncognitoMode()) {
    _backgroundLaunching = true;
    showMessages();
    const userRow = appendUserMsg(text);
    scrollDown();
    let run = null;
    try {
      const { startBackgroundWork } = await import('./aidebackground.js?v=245');
      run = await startBackgroundWork({
        sessionId,
        request: text,
        fileIds: attachmentIds,
        selection: sel,
        selectionSource: getSelectionSource(),
        permissionMode: getPermMode(),
        effort: getEffort(sel?.model),
        reasoningMode: getReasoningMode(sel?.model),
        customEffort: getCustomEffort(sel?.model),
      });
    } catch (error) {
      toast(error?.message || 'could not start background work', 'error');
    } finally {
      _backgroundLaunching = false;
    }
    if (!run) {
      userRow.remove();
      restoreComposerInput(text);
      return;
    }
    clearAttachments();
    if (freshSession) updateSessionName(sessionId, text.slice(0, 54));
    return;
  }

  showMessages();
  appendUserMsg(text, documentScope);
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
    effort: getEffort(sel.model),
    reasoning_mode: getReasoningMode(sel.model),
    custom_effort: getCustomEffort(sel.model),
    context_scope: documentScope || undefined,
  }, { freshSession, pendingDraft });
}

export function retrySavedResponse(request, previousRow) {
  if (!canSendMessage() || getActiveId() !== request.session_id || !previousRow?.isConnected) return false;
  void streamReply(request, { previousRow });
  document.getElementById('composer-ta')?.focus();
  return true;
}

async function streamReply(request, { freshSession = false, previousRow = null, pendingDraft = null } = {}) {
  const { session_id: sessionId, message: text, context_scope: documentScope, incognito: privateReply } = request;
  // Only the latest settled failure may retry. A new turn retires older controls.
  document.querySelectorAll('.aide-retry-response').forEach(button => button.remove());
  previousRow?.remove();
  setStreaming(true);
  const ctrl = new AbortController();
  const streamToken = ++_streamToken;
  _chatAbort = ctrl;
  _chatSessionId = sessionId;

  const { row, body } = createStreamingAiRow();

  let thinkingEl = null;
  const contentEl = document.createElement('div');
  contentEl.className = 'ai-content';
  body.appendChild(contentEl);
  let provenanceEl = null;
  let sourceCitations = null;
  let sourceReplyId = "";
  let agentEl = null;
  let todoEl = null;
  const toolEls = new Map();
  let accText = '';
  let accThink = '';
  let cursor = null;
  let runId = null;
  let hadEdits = false;
  let thinkStart = 0;
  let thinkTimer = 0;
  let thinkDone = false;
  let genStart = 0;     // first answer token time, for tok/s
  let statsEl = null;
  let outTok = 0;       // real output tokens from usage (if provided)
  let providerError = false;
  let sourceUserId = request.retry_message_id || '';
  let receivedDone = false;
  let streamEnded = false;
  let toolActivity = false;
  let rejectedBeforeStart = false;
  const progressEl = document.createElement('div');
  progressEl.className = 'aide-run-progress';
  progressEl.setAttribute('role', 'status');
  progressEl.setAttribute('aria-live', 'polite');
  progressEl.textContent = 'typing';
  body.appendChild(progressEl);
  const setProgress = text => {
    if (progressEl.isConnected) progressEl.textContent = text;
  };
  const clearProgress = () => progressEl.remove();

  const updateStats = (final = false) => {
    if (!genStart) return;
    if (!statsEl) {
      statsEl = document.createElement('div');
      statsEl.className = 'msg-stats';
      body.appendChild(statsEl);
    }
    const secs = (Date.now() - genStart) / 1000;
    const toks = outTok || Math.max(1, Math.round(accText.length / 4));  // real if known, else ~chars/4
    const approx = outTok ? '' : '~';
    const rate = secs > 0.3 ? ` · ${Math.round(toks / secs)} tok/s` : '';
    statsEl.textContent = `${approx}${formatNumber(toks)} tok${rate}`;
  };

  // freeze the thinking block: stop the live timer, show "thought for Xs", collapse
  const finishThinking = () => {
    if (!thinkingEl || thinkDone) return;
    thinkDone = true;
    if (thinkTimer) { clearInterval(thinkTimer); thinkTimer = 0; }
    const secs = Math.max(1, Math.round((Date.now() - thinkStart) / 1000));
    const label = thinkingEl.querySelector('.think-label');
    const timer = thinkingEl.querySelector('.think-timer');
    if (label) label.textContent = `thought for ${secs}s`;
    if (timer) timer.textContent = '';
    thinkingEl.classList.remove('thinking-live');
    thinkingEl.classList.remove('open');
  };

  const addCursor = (target) => {
    cursor = document.createElement('span');
    cursor.className = 'stream-cursor';
    target.appendChild(cursor);
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
    // only auto-scroll if the user is already following along at the bottom
    const chat = document.getElementById('chat');
    const stick = !chat || (chat.scrollHeight - chat.scrollTop - chat.clientHeight < 120);
    cursor?.remove();
    contentEl.innerHTML = mdToHtml(stripEmojis(displayText));
    applyResponsePrivacy(contentEl);
    cursor?.remove();
    addCursor(contentEl);
    updateStats();
    if (stick) scrollDown();
  };
  const scheduleRender = () => {
    if (renderTimer) return;
    const since = Date.now() - lastRenderAt;
    if (since >= 45) flushRender();                       // paint now
    else renderTimer = setTimeout(flushRender, 45 - since); // trailing paint
  };

  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(request),
      signal: ctrl.signal,
    });

    if (!r.ok) {
      const error = await r.json().catch(() => ({}));
      rejectedBeforeStart = r.status === 409 && error.code === 'turn_in_progress';
      const message = typeof error.detail === 'string' ? error.detail : error.detail?.message || 'could not start this answer';
      const chat = document.getElementById('chat');
      const followedReply = chat && chat.scrollHeight - chat.scrollTop - chat.clientHeight < 96;
      body.innerHTML = rejectedBeforeStart
        ? `<div class="error-msg model-error"><p role="status">${escHtml(message)}</p></div>`
        : `<div class="error-msg">${escHtml(message)}</div>`;
      body.classList.add('done');
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

    pendingDraft?.accept();
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    addCursor(body);

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
          // appendChild, not innerHTML += — the latter re-parses all of body and
          // detaches the live tool/agent nodes (toolEls/agentEl) + their listeners
          appendError(body, chunk.error);
          if (isConnError(chunk.error)) showConnBanner();
          continue;
        }

        if (chunk.done && chunk.usage) {
          const u = chunk.usage;
          // openai uses prompt/completion_tokens; anthropic uses input/output_tokens
          const inp = u.prompt_tokens || u.input_tokens || 0;
          const out = u.completion_tokens || u.output_tokens || 0;
          if (out) outTok = out;
          const total = inp + out;
          if (total) {
            const el = document.getElementById('session-token-count');
            const value = document.getElementById('session-token-count-value');
            if (el && value) {
              const formatted = formatNumber(total);
              value.textContent = `${formatted} tok`;
              el.setAttribute('aria-label', `${formatted} tokens used in the latest response`);
              el.hidden = false;
            }
          }
        }

        if (chunk.agent_run) {
          runId = chunk.agent_run.id || runId;
        }

        if (chunk.saved_user?.id) sourceUserId = chunk.saved_user.id;

        if (chunk.saved_message) {
          row.dataset.msgId = chunk.saved_message.id;
          if (typeof chunk.saved_message.content === 'string') accText = chunk.saved_message.content;
          sourceCitations = chunk.saved_message.source_citations;
        }

        if (chunk.context_provenance) {
          sourceReplyId = chunk.context_provenance.reply_id || "";
          provenanceEl?.remove();
          provenanceEl = contextProvenanceElement(chunk.context_provenance);
          if (provenanceEl) body.appendChild(provenanceEl);
        }

        // agent_turn is internal bookkeeping. Keep the user-facing state as
        // "typing" until real thinking or a named tool begins.

        if (chunk.todo_update) {
          const panel = ensureAgentPanel();
          if (!todoEl) {
            todoEl = document.createElement('div');
            todoEl.className = 'agent-todos';
            panel.parentElement.insertBefore(todoEl, panel);
          }
          const items = chunk.todo_update.items || [];
          todoEl.innerHTML = items.map(item => `
            <div class="agent-todo ${escHtml(item.status || 'pending')}">
              <span class="agent-todo-mark"></span>
              <span>${escHtml(item.step || '')}</span>
            </div>
          `).join('');
          scrollDown();
        }

        if (chunk.tool_start) {
          const t = chunk.tool_start;
          setProgress(`${String(t.name || 'tool').replaceAll('_', ' ')}…`);
          const panel = ensureAgentPanel();
          const step = document.createElement('div');
          step.className = 'agent-step running' + (DESTRUCTIVE_TOOLS.has(t.name) ? ' destructive' : '');
          step.dataset.callId = t.call_id || '';
          step.dataset.toolName = t.name || '';
          step.innerHTML = `
            <div class="agent-step-head">
              <span class="agent-step-dot"></span>
              <span class="agent-step-name">${escHtml(t.name || 'tool')}</span>
              <span class="agent-step-summary">${escHtml(toolSummary(t.name, t.args))}</span>
              <span class="agent-step-status">running</span>
            </div>
            <div class="agent-step-args-wrap custom-disclosure">
              <div class="custom-summary" onclick="this.parentElement.classList.toggle('open')">args</div>
              <pre class="agent-step-args custom-details">${escHtml(JSON.stringify(t.args || {}, null, 2))}</pre>
            </div>
            <pre class="agent-step-output"></pre>
          `;
          panel.appendChild(step);
          toolEls.set(t.call_id, step);
          scrollDown();
        }

        if (chunk.tool_delta) {
          const t = chunk.tool_delta;
          const step = toolEls.get(t.call_id);
          const out = step?.querySelector('.agent-step-output');
          if (out) out.textContent += t.text || '';
          scrollDown();
        }

        if (chunk.tool_image) {
          const t = chunk.tool_image;
          const step = toolEls.get(t.call_id);
          if (step && t.image) {
            let shot = step.querySelector('.agent-step-shot');
            if (!shot) {
              shot = document.createElement('img');
              shot.className = 'agent-step-shot';
              step.appendChild(shot);
            }
            shot.src = t.image;
          }
          scrollDown();
        }

        if (chunk.tool_diff) {
          const t = chunk.tool_diff;
          const step = toolEls.get(t.call_id);
          hadEdits ||= canRevertTool(step?.dataset.toolName);
          if (step && t.diff) {
            let d = step.querySelector('.agent-step-diff');
            if (!d) {
              d = document.createElement('pre');
              d.className = 'agent-step-diff';
              step.appendChild(d);
            }
            d.innerHTML = renderDiff(t.diff);
          }
          scrollDown();
        }

        if (chunk.tool_permission) {
          const t = chunk.tool_permission;
          const step = toolEls.get(t.call_id);
          if (step) {
            const card = document.createElement('div');
            card.className = 'agent-perm';
            card.dataset.req = t.request_id;
            card.innerHTML = `
              <div class="agent-perm-msg">approve: <b>${escHtml(toolSummary(t.name, t.args))}</b>?</div>
              <div class="agent-perm-actions">
                <button class="agent-perm-allow">approve</button>
                <button class="agent-perm-deny">deny</button>
              </div>`;
            step.appendChild(card);
            const decide = async (allow) => {
              card.querySelectorAll('button').forEach(b => b.disabled = true);
              await fetch(`/api/agent/permission/${t.request_id}`, {
                method: 'POST',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify({ allow }),
              }).catch(() => {});
              card.classList.add(allow ? 'approved' : 'denied');
              card.querySelector('.agent-perm-msg').textContent = allow ? 'approved' : 'denied';
            };
            card.querySelector('.agent-perm-allow').addEventListener('click', () => decide(true));
            card.querySelector('.agent-perm-deny').addEventListener('click', () => decide(false));
          }
          scrollDown();
        }

        if (chunk.tool_permission_resolved) {
          const t = chunk.tool_permission_resolved;
          const step = toolEls.get(t.call_id);
          const card = step?.querySelector('.agent-perm');
          if (card && !card.classList.contains('approved') && !card.classList.contains('denied')) {
            // resolved elsewhere / timed out
            card.querySelectorAll('button').forEach(b => b.disabled = true);
            card.classList.add(t.allow ? 'approved' : 'denied');
            card.querySelector('.agent-perm-msg').textContent = t.allow ? 'approved' : 'denied';
          }
        }

        if (chunk.user_question) {
          const question = chunk.user_question;
          const step = toolEls.get(question.call_id);
          renderAideQuestion(step || ensureAgentPanel(), question);
          scrollDown();
        }

        if (chunk.user_question_resolved) {
          const resolved = chunk.user_question_resolved;
          const step = toolEls.get(resolved.call_id);
          markAideQuestionResolved(step || agentEl, resolved.id, resolved.answer?.cancelled === true);
        }

        if (chunk.tool_result) {
          const t = chunk.tool_result;
          const step = toolEls.get(t.call_id);
          if (step) {
            step.classList.remove('running');
            step.classList.toggle('error', !!t.error);
            const status = step.querySelector('.agent-step-status');
            if (status) status.textContent = t.completed === false ? 'no final result' : t.error ? 'error' : 'done';
            const out = step.querySelector('.agent-step-output');
            if (out && !out.textContent) out.textContent = t.output || '(no output)';
          }
          scrollDown();
        }

        if (chunk.thinking) {
          setProgress('thinking…');
          accThink += chunk.thinking;
          if (!thinkingEl) {
            thinkStart = Date.now();
            thinkingEl = document.createElement('div');
            thinkingEl.className = 'thinking-block thinking-live custom-disclosure open';
            thinkingEl.innerHTML = `
              <div class="custom-summary" onclick="this.parentElement.classList.toggle('open')">
                <span class="think-label">thinking</span><span class="think-timer"></span>
              </div>
              <div class="thinking-content custom-details"></div>`;
            body.insertBefore(thinkingEl, contentEl);
            // live elapsed timer while reasoning
            thinkTimer = setInterval(() => {
              if (thinkDone) return;
              const t = thinkingEl.querySelector('.think-timer');
              if (t) t.textContent = ` ${((Date.now() - thinkStart) / 1000).toFixed(1)}s`;
            }, 100);
          }
          thinkingEl.querySelector('.thinking-content').textContent = accThink;
          scrollDown();
        }

        if (chunk.delta) {
          finishThinking();   // first real content → reasoning is done
          clearProgress();
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
        toast('reply arrived all at once: a proxy is buffering the stream. using clash? add *.localhost to its system-proxy bypass list', 'error');
      }
    }

  } catch (e) {
    if (getActiveId() === sessionId && _streamToken === streamToken) {
      if (pendingDraft) pendingDraft.restore(accText);
      else if (!previousRow) {
        restoreDocumentScope(documentScope);
        if (documentScope && !accText) restoreComposerInput(text);
      }
    }
    if (e.name !== 'AbortError') {
      appendError(body, `stream error: ${e.message}`);
      if (isConnError(e.message)) showConnBanner();
    }
  } finally {
    if (_chatAbort === ctrl) {
      _chatAbort = null;
      _chatSessionId = null;
    }
    if (_streamToken === streamToken) setStreaming(false);
    if (renderTimer) { clearTimeout(renderTimer); renderTimer = 0; }
    finishThinking();   // freeze timer even if the reply was thinking-only
    clearProgress();
    updateStats(true);  // final token count + tok/s (real if usage was sent)
    cursor?.remove();
    body.classList.add('done');
    if (ctrl.signal.aborted) appendInterruptionNotice(body);
    else if (streamEnded && !receivedDone && !providerError) {
      appendInterruptionNotice(body, 'response ended before completion was confirmed. review any partial answer and task activity before sending again.');
    }

    if (agentEl && (toolEls.size || todoEl)) {
      const hasAttention = Boolean(
        agentEl.querySelector('.agent-step.error, .agent-step.running, .agent-perm:not(.approved):not(.denied), .aide-question-card:not(.answered):not(.cancelled)')
      );
      agentEl.classList.toggle('open', hasAttention);
      const summary = agentEl.querySelector('.custom-summary');
      if (summary) {
        summary.textContent = hasAttention ? 'run details need attention' : 'run details';
        summary.setAttribute('aria-expanded', String(hasAttention));
      }
    } else if (agentEl) {
      agentEl.remove();
      agentEl = null;
    }

    // provenance — let the reader see what the run actually touched
    if (agentEl && runId) {
      const sum = agentEl.querySelector('.custom-summary') || agentEl.querySelector('summary');
      if (sum && !sum.querySelector('.agent-sources-btn')) {
        const sb = document.createElement('button');
        sb.className = 'agent-sources-btn';
        sb.textContent = 'sources';
        sb.title = 'files, urls, searches and commands this run touched';
        let panel = null;
        sb.addEventListener('click', async (e) => {
          e.preventDefault(); e.stopPropagation();
          if (panel) { panel.hidden = !panel.hidden; return; }
          sb.disabled = true;
          try {
            const src = await fetch(`/api/agent/runs/${runId}/sources`).then(x => x.json());
            const { sourcesHtml } = await import('./runs.js');
            panel = document.createElement('div');
            panel.className = 'agent-sources';
            panel.innerHTML = sourcesHtml(src);
            agentEl.appendChild(panel);
          } catch { toast('couldn’t load sources', 'error'); }
          sb.disabled = false;
        });
        sum.appendChild(sb);
      }
    }

    // revert control — only if the agent actually edited files this run
    if (agentEl && runId && hadEdits) {
      const sum = agentEl.querySelector('.custom-summary') || agentEl.querySelector('summary');
      if (sum && !sum.querySelector('.agent-revert-btn')) {
        const rb = document.createElement('button');
        rb.className = 'agent-revert-btn';
        rb.textContent = 'revert edits';
        rb.title = 'restore every file this run changed';
        rb.addEventListener('click', async (e) => {
          e.preventDefault(); e.stopPropagation();
          rb.disabled = true; rb.textContent = 'reverting…';
          try {
            const r = await fetch(`/api/agent/runs/${runId}/revert`, { method: 'POST' }).then(x => x.json());
            rb.textContent = `reverted ${r.restored || 0}`;
            toast(`reverted ${r.restored || 0} file(s)`, 'success');
          } catch { rb.textContent = 'revert failed'; toast('revert failed', 'error'); }
        });
        sum.appendChild(rb);
      }
    }

    const artifacts = extractArtifacts(accText);
    const cleanText = stripArtifacts(accText);

    // finalize display — strip artifact tags from rendered markdown
    if (cleanText) {
      if (!contentEl) {
        contentEl = document.createElement('div');
        contentEl.className = 'ai-content';
        body.appendChild(contentEl);
      }
      contentEl.innerHTML = mdToHtml(stripEmojis(cleanText));
      applyResponsePrivacy(contentEl);
    }

    // Retry a definite refusal before the turn is accepted, or a finished provider failure.
    // Unknown transport outcomes must not replay work that might already have happened.
    if (rejectedBeforeStart || (sourceUserId && providerError && receivedDone && streamEnded && !ctrl.signal.aborted && !accText && !toolActivity && !(privateReply && request.file_ids.length))) {
      const retry = document.createElement('button');
      retry.type = 'button'; retry.className = 'btn aide-retry-response'; retry.textContent = 'retry response';
      retry.addEventListener('click', () => {
        if (!canSendMessage() || getActiveId() !== sessionId || _streamToken !== streamToken || !row.isConnected) return;
        const restoreFocus = document.activeElement === retry;
        void streamReply(rejectedBeforeStart ? request : { ...request, retry_message_id: sourceUserId }, { freshSession, previousRow: row, pendingDraft: rejectedBeforeStart ? pendingDraft : null });
        if (restoreFocus) document.getElementById('composer-ta')?.focus();
      });
      body.querySelector('.error-msg')?.appendChild(retry);
    }

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
    if (wrap && (cleanText || artifacts.length)) {
      const actions = document.createElement('div');
      actions.className = 'msg-actions';
      let html = '';
      if (cleanText) {
        html += `<button class="act-btn" onclick="copyMsg(this)">copy</button>`;
        html += `<button class="act-btn" onclick="saveMsgAs(this,'note')" title="save this reply as a note">+note</button>`;
        html += `<button class="act-btn" onclick="saveMsgAs(this,'task')" title="${t('aide.review_plan_task')}">${t('aide.add_plan_task')}</button>`;
        html += `<button class="msg-rewrite-btn act-btn" data-style="shorter" title="rewrite shorter">shorter</button>`;
        html += `<button class="msg-rewrite-btn act-btn" data-style="simpler" title="rewrite simpler">simpler</button>`;
      }
      if (artifacts.length) {
        wrap.dataset.artifacts = JSON.stringify(artifacts);
        html += `<button class="act-btn" onclick="openArtifactFromMsg(this)">open artifact</button>`;
      }
      actions.innerHTML = html;
      wrap.appendChild(actions);
      if (cleanText) import('./sessions.js').then(m => m.wireRewriteButtons(actions));
    }

    // auto-open the first artifact
    if (artifacts.length) {
      const a = artifacts[0];
      openArtifact(a.content, a.type, a.title, a.lang);
    }

    scrollDown();

    // name the chat from its first message (async; updates the sidebar when ready)
    if (freshSession && !privateReply && cleanText && row.dataset.msgId) {
      fetch(`/api/sessions/${sessionId}/auto-name`, { method: 'POST' })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d?.name) updateSessionName(sessionId, d.name); })
        .catch(() => {});
    }
  }

  function ensureAgentPanel() {
    if (agentEl) return agentEl.querySelector('.agent-step-list');
    agentEl = document.createElement('div');
    agentEl.className = 'agent-steps custom-disclosure open';
    agentEl.innerHTML = `
      <div class="custom-summary" role="button" tabindex="0" aria-expanded="true">run details</div>
      <div class="agent-step-list custom-details"></div>`;
    body.appendChild(agentEl);
    const disclosure = agentEl.querySelector('.custom-summary');
    disclosure.addEventListener('click', event => {
      const open = agentEl.classList.toggle('open');
      event.currentTarget.setAttribute('aria-expanded', String(open));
      event.currentTarget.textContent = 'run details';
    });
    disclosure.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        disclosure.click();
      }
    });
    return agentEl.querySelector('.agent-step-list');
  }
}


function _splitBeforeArtifact(text) {
  const idx = text.indexOf('<aide-artifact');
  return idx === -1 ? text : text.slice(0, idx).trimEnd();
}

function renderDiff(diff = '') {
  return String(diff).split('\n').map(line => {
    let cls = '';
    if (line.startsWith('+') && !line.startsWith('+++')) cls = 'diff-add';
    else if (line.startsWith('-') && !line.startsWith('---')) cls = 'diff-del';
    else if (line.startsWith('@@')) cls = 'diff-hunk';
    else if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff ')) cls = 'diff-meta';
    return `<span class="${cls}">${escHtml(line)}</span>`;
  }).join('\n');
}

function escHtml(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// append an error line without nuking the live message DOM (textContent = no escaping needed)
function appendError(body, msg) {
  const el = document.createElement('div');
  el.className = 'error-msg';
  const detail = String(msg || 'the model returned an error');
  const status = Number(detail.match(/HTTP\s+(\d{3})/i)?.[1]);
  const connectionFailure = isConnError(detail);
  if (status || connectionFailure) {
    el.classList.add('model-error');
    const explanation = document.createElement('p');
    explanation.setAttribute('role', 'status');
    explanation.textContent = connectionFailure
      ? 'the model could not be reached. check its connection in model settings, then try again.'
      : status === 404
      ? 'the model could not be found. check the selected model and connection in model settings, then try again.'
      : [401, 403].includes(status)
      ? 'the model did not authorize this request. check its credentials in model settings, then try again.'
      : status === 429
      ? 'the model is busy or has reached its limit. wait a moment, then try again.'
      : status >= 500
      ? 'the model service is temporarily unavailable. try again later, or check its connection in model settings.'
      : 'the model could not answer this request. check the model and connection in model settings, then try again.';
    const settings = document.createElement('button');
    settings.type = 'button'; settings.className = 'btn'; settings.textContent = 'model settings';
    settings.addEventListener('click', () => window._openSettings?.('models'));
    const details = document.createElement('details');
    const summary = document.createElement('summary'); summary.textContent = 'error details';
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
  m.textContent = 'the model connection is unavailable. check the failed response for details and recovery options.';
  b.style.display = 'flex';
}

export function hideConnBanner() {
  const b = document.getElementById('conn-banner');
  if (b) b.style.display = 'none';
}

function setStreaming(val, stoppable = true) {
  _streaming = val;
  document.getElementById('send-btn').disabled = val;
  const stop = document.getElementById('stop-btn');
  stop.classList.toggle('visible', val && stoppable);
}


export function stopStream() {
  const sid = _chatSessionId;
  _chatAbort?.abort();
  _chatAbort = null;
  _chatSessionId = null;
  if (sid) fetch(`/api/chat/stop/${sid}`, { method: 'POST' }).catch(() => {});
  setStreaming(false);
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
  appendUserMsg(prompt);
  clearAttachments();
  scrollDown();
  const { body } = createStreamingAiRow();
  let error, retry;
  const send = async (again = false) => {
    setStreaming(true, false);
    if (again) {
      retry.setAttribute('aria-disabled', 'true');
      retry.textContent = 'retrying…';
      error.setAttribute('role', 'status');
      error.textContent = 'checking saved image…';
    } else {
      const status = document.createElement('div');
      status.className = 'ai-content img-gen-status';
      status.setAttribute('role', 'status');
      status.textContent = 'generating image…';
      body.replaceChildren(status);
    }
    scrollDown();
    try {
      const r = await fetch('/api/images/chat', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify(request),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'generation failed');
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
      toast(d.doc_id ? 'saved to notes' : 'image generated', 'success');
    } catch (e) {
      if (!error) {
        error = document.createElement('div');
        error.className = 'ai-content';
        const template = document.createElement('template');
        template.innerHTML = '<button type="button" class="act-btn img-gen-retry">retry image</button>';
        retry = template.content.firstElementChild;
        retry.addEventListener('click', () => { if (!_streaming) void send(true); });
      }
      error.setAttribute('role', 'alert');
      error.textContent = 'could not confirm image: ' + (e.message || 'request failed');
      retry.removeAttribute('aria-disabled');
      retry.textContent = 'retry image';
      if (!again) body.replaceChildren(error, retry);
      toast(e.message || 'generation failed', 'error');
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

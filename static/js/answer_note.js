import { requestId } from './request_id.js';
import { saveNote, showNoteRecovery } from './note_capture.js';
import { mdToHtml, plainError } from './util.js';
import { stripArtifacts } from './artifacts.js';
import { applyResponsePrivacy, stripEmojis } from './privacy.js';
import { sourceCitationStatus } from './memoryactions.js';
import { t } from './i18n.js';
import { dismissAfter } from './notice.js';

const savedAnswers = new Map();

function noteSourceKey(wrap, create = false) {
  const session = wrap.dataset.sessionId;
  const message = wrap.closest('.msg-row')?.dataset.msgId;
  if (wrap.dataset.private !== 'true' && session && message) return `aide:${session}:${message}`;
  if (create && !wrap.noteSaveKey) wrap.noteSaveKey = `aide-local:${requestId()}`;
  return wrap.noteSaveKey || '';
}

function answerNoteText(wrap) {
  const session = wrap.dataset.sessionId;
  const origin = session && wrap.dataset.private !== 'true'
    ? `\n\n[from Aide](/?app=aide#${encodeURIComponent(session)})`
    : '\n\nsaved from a private Aide conversation';
  return wrap.answerText.trim() + origin;
}

export function reconcileAnswerNote(wrap) {
  const entry = savedAnswers.get(noteSourceKey(wrap));
  if (!entry || !wrap.answerText?.trim() || entry.text !== answerNoteText(wrap)) return;
  wrap.savedNote = entry.saved;
  const button = wrap.querySelector('button[data-msg-act="note"]');
  if (button) button.textContent = t('aide.saved_note');
}

export async function reconcileSourceReply(wrap, kind = 'note') {
  if (!wrap.pendingSourceReply) return;
  const action = kind === 'task' ? t('aide.add_plan_task') : t('aide.note_button');
  if (!wrap.sourceReplyId) throw new Error(t(kind === 'task' ? 'aide.source_refs_unavailable_task' : 'aide.source_refs_unavailable_note'));
  const response = await fetch(`/api/sessions/${encodeURIComponent(wrap.dataset.sessionId)}/history`, { signal: AbortSignal.timeout(15000) });
  if (!response.ok) throw new Error(t('aide.source_refs_check_failed', { action }));
  const history = await response.json();
  const reply = history.messages?.find(message => message.role === 'assistant'
    && message.meta?.context_provenance?.reply_id === wrap.sourceReplyId);
  if (!reply?.meta?.source_citations || typeof reply.content !== 'string') {
    throw new Error(t('aide.source_refs_pending', { action }));
  }
  const row = wrap.closest('.msg-row');
  if (row && typeof reply.id === 'string') row.dataset.msgId = reply.id;
  wrap.answerText = stripArtifacts(reply.content);
  wrap.pendingSourceReply = false;
  const content = wrap.querySelector('.ai-content');
  if (content) {
    content.innerHTML = mdToHtml(stripEmojis(wrap.answerText));
    applyResponsePrivacy(content);
  }
  wrap.querySelector('.source-citation-status')?.replaceWith(sourceCitationStatus(reply.meta.source_citations));
}

async function openAnswerNote(path) {
  if (!(await window._openSearchResult?.('note', path))) throw new Error(t('aide.note_open_failed'));
}

function noteSaved(saved, text, focus = false, _body = null, sourceKey = '') {
  if (typeof sourceKey === 'string' && /^aide(?::|-local:)/.test(sourceKey)) {
    savedAnswers.set(sourceKey, { saved, text });
    document.querySelectorAll('.ai-wrap').forEach(reconcileAnswerNote);
  }
  const host = document.getElementById('aide-note-recovery');
  if (!host) return;
  host.dataset.savedNoteRequest = saved.request_id;
  const status = document.createElement('p'); status.setAttribute('role', 'status');
  status.textContent = t('aide.note_saved_to', { path: saved.path });
  const open = document.createElement('button'); open.type = 'button'; open.className = 'btn note-saved-open'; open.textContent = t('aide.note_open');
  open.onclick = async () => {
    try { await openAnswerNote(saved.path); }
    catch (error) { status.textContent = plainError(error.message); }
  };
  host.replaceChildren(status, open);
  if (focus && host.getClientRects().length) open.focus();
  dismissAfter(host);
}

export async function loadAnswerNoteRecovery() {
  const host = document.getElementById('aide-note-recovery');
  if (host) await showNoteRecovery(host, noteSaved, openAnswerNote, () => document.getElementById('composer-ta'));
}

export async function saveAnswerNote(button) {
  if (button.disabled) return;
  const wrap = button.closest('.ai-wrap');
  if (!wrap?.answerText?.trim()) return;
  reconcileAnswerNote(wrap);
  if (wrap.savedNote) { noteSaved(wrap.savedNote, '', true); return; }
  const focusBefore = document.activeElement;
  const restoreFocus = () => document.activeElement === focusBefore || document.activeElement === document.body;
  button.disabled = true; button.textContent = t('common.saving');
  try {
    await reconcileSourceReply(wrap);
    const raw = wrap.answerText.trim();
    const text = answerNoteText(wrap);
    const sourceKey = noteSourceKey(wrap, true);
    // a line ending in "." left "ok..md"; trailing dots and spaces go before the extension
    const title = raw.split('\n')[0].replace(/[#*`\[\]<>:/\\?"|]/g, '').trim().slice(0, 80).replace(/[.\s]+$/, '') || 'answer';
    const saved = await saveNote(text, `${title}.md`, { sourceKey });
    wrap.savedNote = saved;
    noteSaved(saved, text, restoreFocus(), null, sourceKey);
  } catch (error) {
    const host = document.getElementById('aide-note-recovery');
    if (host) {
      const status = document.createElement('p'); status.setAttribute('role', 'status'); status.textContent = plainError(error.message);
      host.replaceChildren(status);
      await loadAnswerNoteRecovery();
      // Checking a stopped reply may fail before a note receipt exists.
      if (!host.contains(status)) host.prepend(status);
      if (restoreFocus()) host.querySelector('.note-retry, .note-recovery-error button')?.focus();
    }
  } finally {
    button.disabled = false; button.textContent = wrap.savedNote ? t('aide.saved_note') : t('aide.note_button');
  }
}

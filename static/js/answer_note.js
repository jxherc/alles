import { saveNote, showNoteRecovery } from './note_capture.js';
import { mdToHtml } from './util.js';
import { stripArtifacts } from './artifacts.js';
import { applyResponsePrivacy, stripEmojis } from './privacy.js';
import { sourceCitationStatus } from './memoryactions.js';

export async function reconcileSourceReply(wrap, kind = 'note') {
  if (!wrap.pendingSourceReply) return;
  if (!wrap.sourceReplyId) throw new Error(`saved source references are unavailable; reopen this chat before saving a ${kind}`);
  const response = await fetch(`/api/sessions/${encodeURIComponent(wrap.dataset.sessionId)}/history`, { signal: AbortSignal.timeout(15000) });
  if (!response.ok) throw new Error(`could not check saved source references; try +${kind} again`);
  const history = await response.json();
  const reply = history.messages?.find(message => message.role === 'assistant'
    && message.meta?.context_provenance?.reply_id === wrap.sourceReplyId);
  if (!reply?.meta?.source_citations || typeof reply.content !== 'string') {
    throw new Error(`source references are still being saved; try +${kind} again`);
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
  if (!(await window._openSearchResult?.('note', path))) throw new Error('could not open the saved note');
}

function noteSaved(saved, _text, focus = false) {
  const host = document.getElementById('aide-note-recovery');
  if (!host) return;
  host.dataset.savedNoteRequest = saved.request_id;
  const status = document.createElement('p'); status.setAttribute('role', 'status');
  status.textContent = `saved to ${saved.path}`;
  const open = document.createElement('button'); open.type = 'button'; open.className = 'btn note-saved-open'; open.textContent = 'open note';
  open.onclick = async () => {
    try { await openAnswerNote(saved.path); }
    catch (error) { status.textContent = error.message; }
  };
  host.replaceChildren(status, open);
  if (focus && host.getClientRects().length) open.focus();
}

export async function loadAnswerNoteRecovery() {
  const host = document.getElementById('aide-note-recovery');
  if (host) await showNoteRecovery(host, noteSaved, openAnswerNote, () => document.getElementById('composer-ta'));
}

export async function saveAnswerNote(button) {
  if (button.disabled) return;
  const wrap = button.closest('.ai-wrap');
  if (!wrap?.answerText?.trim()) return;
  if (wrap.savedNote) { noteSaved(wrap.savedNote, '', true); return; }
  const session = wrap.dataset.sessionId;
  const origin = session && wrap.dataset.private !== 'true'
    ? `\n\n[from Aide](/?app=aide#${encodeURIComponent(session)})`
    : '\n\nsaved from a private Aide conversation';
  const focusBefore = document.activeElement;
  const restoreFocus = () => document.activeElement === focusBefore || document.activeElement === document.body;
  button.disabled = true; button.textContent = 'saving…';
  try {
    await reconcileSourceReply(wrap);
    const raw = wrap.answerText.trim();
    const text = raw + origin;
    const title = raw.split('\n')[0].replace(/[#*`\[\]<>:/\\?"|]/g, '').trim().slice(0, 80) || 'answer';
    const saved = await saveNote(text, `${title}.md`);
    wrap.savedNote = saved;
    noteSaved(saved, text, restoreFocus());
  } catch (error) {
    const host = document.getElementById('aide-note-recovery');
    if (host) {
      const status = document.createElement('p'); status.setAttribute('role', 'status'); status.textContent = error.message;
      host.replaceChildren(status);
      await loadAnswerNoteRecovery();
      // Checking a stopped reply may fail before a note receipt exists.
      if (!host.contains(status)) host.prepend(status);
      if (restoreFocus()) host.querySelector('.note-retry, .note-recovery-error button')?.focus();
    }
  } finally {
    button.disabled = false; button.textContent = wrap.savedNote ? 'saved note' : '+note';
  }
}

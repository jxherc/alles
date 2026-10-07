import { openCaptureReview, showPendingCapture } from './capture.js';
import { reconcileSourceReply } from './answer_note.js';
import { t } from './i18n.js';
import { refreshScrollFollow } from './scrollfollow.js';

const identity = /^[a-zA-Z0-9_-]{1,160}$/;
let preparation = 0;

function taskSaved(saved, kind, focus = false) {
  const host = document.getElementById('aide-task-saved');
  if (!host) return;
  document.getElementById('aide-task-recovery')
    ?.querySelectorAll(':scope > [role="status"]').forEach(node => node.remove());
  const status = document.createElement('p'); status.setAttribute('role', 'status');
  status.textContent = `saved in plan: ${saved.title}`;
  const open = document.createElement('button');
  open.type = 'button'; open.className = 'btn'; open.textContent = 'open in plan';
  open.onclick = async () => {
    if (!(await window._openRecord?.(kind === 'event' ? 'calendar' : 'tasks', saved.id))) {
      status.textContent = 'could not open the saved item; try again';
    }
  };
  host.replaceChildren(status, open);
  refreshScrollFollow();
  if (focus && host.getClientRects().length) open.focus();
  return open;
}

export async function loadAnswerTaskRecovery() {
  const host = document.getElementById('aide-task-recovery');
  if (host) await showPendingCapture(host, taskSaved);
}

export async function saveAnswerTask(button) {
  if (button.getAttribute('aria-disabled') === 'true') return;
  const wrap = button.closest('.ai-wrap');
  if (!wrap?.answerText?.trim()) return;
  const attempt = ++preparation;
  const current = () => attempt === preparation && button.isConnected && button.getClientRects().length;
  if (wrap.savedTask) { taskSaved(wrap.savedTask, 'task', true); return; }
  button.setAttribute('aria-disabled', 'true');
  button.textContent = 'preparing…';
  try {
    await reconcileSourceReply(wrap, 'task');
    if (!current()) return;
    const raw = wrap.answerText.trim();
    const privateReply = wrap.dataset.private === 'true';
    const sessionId = privateReply ? '' : wrap.dataset.sessionId;
    const messageId = privateReply ? '' : wrap.closest('.msg-row')?.dataset.msgId;
    if (!privateReply && (!identity.test(sessionId || '') || !identity.test(messageId || ''))) {
      throw new Error('this reply has not been confirmed. reopen this chat and try again.');
    }
    const excerpt = Array.from(raw).slice(0, 6000).join('');
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(excerpt));
    if (!current()) return;
    const fingerprint = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
    const source = { kind: 'aide', label: 'original Aide reply', excerpt, fingerprint,
      private: privateReply, session_id: sessionId, message_id: messageId };
    const title = raw.split('\n')[0].replace(/[#*`\[\]]/g, '').trim().slice(0, 200) || 'task from Aide';
    await openCaptureReview({ kind: 'task', candidate: { title, notes: raw }, source }, button, (saved, kind) => {
      const origin = saved.source;
      if (kind === 'task' && origin?.kind === 'aide' && origin.fingerprint === fingerprint
          && origin.session_id === sessionId && origin.message_id === messageId && origin.private === privateReply) {
        wrap.savedTask = saved;
        button.textContent = t('aide.saved_plan_task');
      }
      return taskSaved(saved, kind);
    });
  } catch (error) {
    if (!current()) return;
    const host = document.getElementById('aide-task-recovery');
    if (host) {
      const status = document.createElement('p'); status.setAttribute('role', 'status');
      status.textContent = error.message || 'could not prepare this task; try again';
      host.replaceChildren(status);
      await loadAnswerTaskRecovery();
    }
  } finally {
    button.removeAttribute('aria-disabled');
    button.textContent = wrap.savedTask ? t('aide.saved_plan_task') : t('aide.add_plan_task');
  }
}

import { plainError } from './util.js';
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
  status.textContent = t('aide.task_saved_in_plan', { title: saved.title });
  const open = document.createElement('button');
  open.type = 'button'; open.className = 'btn'; open.textContent = t('aide.task_open_in_plan');
  open.onclick = async () => {
    if (!(await window._openRecord?.(kind === 'event' ? 'calendar' : 'tasks', saved.id))) {
      status.textContent = t('aide.task_open_failed');
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
  // Reply menus close before dispatch. Use their surviving visible opener for
  // async ownership checks and review focus, retaining the original source button.
  const trigger = button.closest('.msg-actions-menu')
    ? button.closest('.msg-actions')?.querySelector('.msg-more-trigger') || button
    : button;
  const attempt = ++preparation;
  const current = () => attempt === preparation && button.isConnected
    && trigger.isConnected && trigger.getClientRects().length;
  if (wrap.savedTask) { taskSaved(wrap.savedTask, 'task', true); return; }
  button.setAttribute('aria-disabled', 'true');
  button.textContent = t('aide.task_preparing');
  try {
    await reconcileSourceReply(wrap, 'task');
    if (!current()) return;
    const raw = wrap.answerText.trim();
    const privateReply = wrap.dataset.private === 'true';
    const sessionId = privateReply ? '' : wrap.dataset.sessionId;
    const messageId = privateReply ? '' : wrap.closest('.msg-row')?.dataset.msgId;
    if (!privateReply && (!identity.test(sessionId || '') || !identity.test(messageId || ''))) {
      throw new Error(t('aide.task_reply_unconfirmed'));
    }
    const excerpt = Array.from(raw).slice(0, 6000).join('');
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(excerpt));
    if (!current()) return;
    const fingerprint = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
    const source = { kind: 'aide', label: t('aide.task_source_label'), excerpt, fingerprint,
      private: privateReply, session_id: sessionId, message_id: messageId };
    const title = raw.split('\n')[0].replace(/[#*`\[\]]/g, '').trim().slice(0, 200) || t('aide.task_default_title');
    await openCaptureReview({ kind: 'task', candidate: { title, notes: raw }, source }, trigger, (saved, kind) => {
      const origin = saved.source;
      if (kind === 'task' && origin?.kind === 'aide' && origin.fingerprint === fingerprint
          && origin.session_id === sessionId && origin.message_id === messageId && origin.private === privateReply) {
        wrap.savedTask = saved;
        button.textContent = t('aide.saved_plan_task');
      }
      return taskSaved(saved, kind);
    }, current);
  } catch (error) {
    if (!current()) return;
    const host = document.getElementById('aide-task-recovery');
    if (host) {
      const status = document.createElement('p'); status.setAttribute('role', 'status');
      status.textContent = plainError(error.message || t('aide.task_prepare_failed'));
      host.replaceChildren(status);
      await loadAnswerTaskRecovery();
    }
  } finally {
    button.removeAttribute('aria-disabled');
    button.textContent = wrap.savedTask ? t('aide.saved_plan_task') : t('aide.add_plan_task');
  }
}

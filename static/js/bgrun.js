// 10b — reattach to a durable background agent run when a session is (re)opened.
// the run keeps going server-side even if the tab closed; we tail its persisted
// events + accumulated prose and show progress instead of an empty chat.

import { renderAideQuestion } from './aidequestions.js?v=1';

let _timer = null;
let _curRun = null;

export function stop() {
  if (_timer) { clearInterval(_timer); _timer = null; }
  _curRun = null;
}

function _box() {
  let b = document.getElementById('bg-reattach');
  if (!b) {
    b = document.createElement('div');
    b.id = 'bg-reattach';
    b.className = 'bg-reattach';
    b.innerHTML = '<span class="bg-reattach-status">↻ running in background…</span>'
      + '<div class="bg-reattach-text"></div><div class="bg-reattach-question"></div>';
    document.getElementById('messages')?.appendChild(b);
  }
  return b;
}

export async function reattach(sessionId) {
  stop();
  if (!sessionId) return;
  let active;
  try {
    active = await fetch(`/api/agent/runs/active?session_id=${encodeURIComponent(sessionId)}`).then(r => r.json());
  } catch { return; }
  if (!active || !active.id || active.status !== 'running') return;

  _curRun = active.id;
  const box = _box();
  if (active.pending_question) {
    renderAideQuestion(box.querySelector('.bg-reattach-question'), active.pending_question);
  }
  let cursor = 0;

  const tick = async () => {
    if (!_curRun) return;
    let d;
    try {
      d = await fetch(`/api/agent/runs/${_curRun}/events?since=${cursor}`).then(r => r.json());
    } catch { return; }
    cursor = (d && typeof d.next === 'number') ? d.next : cursor;
    const txt = box.querySelector('.bg-reattach-text');
    if (txt && d && d.text) txt.textContent = d.text;
    if (d?.pending_question) {
      renderAideQuestion(box.querySelector('.bg-reattach-question'), d.pending_question);
    }
    if (d && d.done) {
      stop();
      const st = box.querySelector('.bg-reattach-status');
      if (st) st.textContent = '✓ finished';
      // give the saved reply a moment to land, then refresh the conversation
      setTimeout(() => { box.remove(); window._reloadActiveSession?.(); }, 800);
    }
  };

  await tick();
  _timer = setInterval(tick, 1200);
}

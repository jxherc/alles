import { mdToHtml, toast } from './util.js';
import {
  appendUserMsg, createStreamingAiRow, scrollDown,
  showMessages, updateSessionName, createSession, getActiveId,
} from './sessions.js';
import { getSelected, getCurrentEndpoint } from './models.js';

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

let _streaming = false;
let _bgStreams = new Map();   // session_id → partial accumulated text (for background streams)

export function isStreaming() { return _streaming; }


export async function sendMessage(text) {
  if (!text?.trim() || _streaming) return;

  let sessionId = getActiveId();

  // no active session — create one
  if (!sessionId) {
    const ep = getCurrentEndpoint();
    if (!ep) { toast('no endpoint configured — add one via the model picker', 'error'); return; }
    const model = getSelected()?.model || ep.models[0] || '';
    const s = await createSession(model, ep.id);
    if (!s) { toast('failed to create session', 'error'); return; }
    sessionId = s.id;
  }

  const sel = getSelected();
  if (!sel) { toast('select a model first', 'error'); return; }

  showMessages();
  appendUserMsg(text);
  scrollDown();

  setStreaming(true);

  const { row, body } = createStreamingAiRow();

  let thinkingEl = null;
  let contentEl = null;
  let accText = '';
  let accThink = '';
  let cursor = null;

  const addCursor = (target) => {
    cursor = document.createElement('span');
    cursor.className = 'stream-cursor';
    target.appendChild(cursor);
  };

  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        message: text,
        mode: getMode(),
      }),
    });

    if (!r.ok) {
      const err = await r.text();
      body.innerHTML = `<div class="error-msg">${err}</div>`;
      body.classList.add('done');
      setStreaming(false);
      return;
    }

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    addCursor(body);

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      const lines = buf.split('\n');
      buf = lines.pop();  // last incomplete line stays in buffer

      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        const raw = line.slice(5).trim();
        if (raw === '[DONE]') break;

        let chunk;
        try { chunk = JSON.parse(raw); } catch { continue; }

        if (chunk.error) {
          cursor?.remove();
          body.innerHTML += `<div class="error-msg">${chunk.error}</div>`;
          break;
        }

        if (chunk.thinking) {
          accThink += chunk.thinking;
          if (!thinkingEl) {
            thinkingEl = document.createElement('div');
            thinkingEl.className = 'thinking-block';
            body.insertBefore(thinkingEl, body.firstChild);
          }
          thinkingEl.textContent = accThink;
          scrollDown();
        }

        if (chunk.delta) {
          accText += chunk.delta;
          if (!contentEl) {
            contentEl = document.createElement('div');
            contentEl.className = 'ai-content';
            cursor?.remove();
            body.appendChild(contentEl);
            addCursor(contentEl);
          }
          // re-render incrementally
          contentEl.innerHTML = mdToHtml(accText);
          cursor?.remove();
          addCursor(contentEl);
          scrollDown();
        }
      }
    }

  } catch (e) {
    if (e.name !== 'AbortError') {
      body.innerHTML += `<div class="error-msg">stream error: ${e.message}</div>`;
    }
  } finally {
    cursor?.remove();
    body.classList.add('done');

    // finalize render
    if (contentEl && accText) {
      contentEl.innerHTML = mdToHtml(accText);
    }

    // action buttons
    const wrap = body.parentElement;
    if (wrap && accText) {
      const actions = document.createElement('div');
      actions.className = 'msg-actions';
      actions.innerHTML = `<button class="act-btn" onclick="copyMsg(this)">copy</button>`;
      wrap.appendChild(actions);
    }

    setStreaming(false);
    scrollDown();
  }
}


function setStreaming(val) {
  _streaming = val;
  document.getElementById('send-btn').disabled = val;
  const stop = document.getElementById('stop-btn');
  stop.classList.toggle('visible', val);
}


export function stopStream() {
  const sid = getActiveId();
  if (sid) fetch(`/api/chat/stop/${sid}`, { method: 'POST' }).catch(() => {});
  setStreaming(false);
}


function getMode() {
  return document.getElementById('mode-agent').classList.contains('active') ? 'agent' : 'chat';
}

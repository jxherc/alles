import { mdToHtml, toast } from './util.js';
import {
  appendUserMsg, createStreamingAiRow, scrollDown,
  showMessages, updateSessionName, createSession, getActiveId, markActive,
} from './sessions.js';
import { getSelected, getCurrentEndpoint } from './models.js';
import { openArtifact, extractArtifacts, stripArtifacts } from './artifacts.js';
import { getAttachments, clearAttachments } from './uploads.js';
import { isIncognitoMode, getPermMode, getEffort } from './modes.js';
import { applyResponsePrivacy, stripEmojis } from './privacy.js';

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

// open artifact from msg actions row
window.openArtifactFromMsg = function(btn) {
  const wrap = btn.closest('.ai-wrap');
  const raw = wrap?.dataset.artifacts;
  if (!raw) return;
  const [a] = JSON.parse(raw);
  if (a) openArtifact(a.content, a.type, a.title, a.lang);
};

let _streaming = false;
let _bgStreams = new Map();   // session_id → partial accumulated text (for background streams)

export function isStreaming() { return _streaming; }


export async function sendMessage(text) {
  if (!text?.trim() || _streaming) return;

  let sessionId = getActiveId();
  let freshSession = false;

  // no active session — create one lazily now (first message)
  if (!sessionId) {
    const ep = getCurrentEndpoint();
    if (!ep) { toast('no endpoint configured — add one via the model picker', 'error'); return; }
    const model = getSelected()?.model || ep.models[0] || '';
    const s = await createSession(model, ep.id, { incognito: isIncognitoMode() });
    if (!s) { toast('failed to create session', 'error'); return; }
    sessionId = s.id;
    freshSession = true;     // first message ever → auto-name it after the reply
    markActive(sessionId);   // highlight + set active, don't re-render
  }

  const sel = getSelected();
  if (!sel) { toast('select a model first', 'error'); return; }

  showMessages();
  appendUserMsg(text);
  clearAttachments();
  scrollDown();

  setStreaming(true);

  const { row, body } = createStreamingAiRow();

  let thinkingEl = null;
  let contentEl = null;
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
    statsEl.textContent = `${approx}${toks.toLocaleString()} tok${rate}` + (final ? '' : ' ▍');
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
    thinkingEl.open = false;
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
    if (!contentEl) {
      contentEl = document.createElement('div');
      contentEl.className = 'ai-content';
      cursor?.remove();
      body.appendChild(contentEl);
    }
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
      body: JSON.stringify({
        session_id: sessionId,
        message: text,
        mode: getMode(),
        file_ids: getAttachments(),
        incognito: isIncognitoMode(),
        permission_mode: getMode() === 'agent' ? getPermMode() : '',
        effort: getMode() === 'agent' ? getEffort() : '',
      }),
    });

    if (!r.ok) {
      const err = await r.text();
      body.innerHTML = `<div class="error-msg">${escHtml(err)}</div>`;
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
          body.innerHTML += `<div class="error-msg">${escHtml(chunk.error)}</div>`;
          if (isConnError(chunk.error)) showConnBanner(chunk.error);
          break;
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
            if (el) { el.textContent = `${total.toLocaleString()} tok`; el.style.display = ''; }
          }
        }

        if (chunk.agent_run) {
          runId = chunk.agent_run.id || runId;
        }

        if (chunk.agent_turn) {
          const t = chunk.agent_turn;
          const panel = ensureAgentPanel();
          let status = agentEl.querySelector('.agent-turn-status');
          if (!status) {
            status = document.createElement('div');
            status.className = 'agent-turn-status';
            panel.parentElement.insertBefore(status, panel);
          }
          status.textContent = `turn ${t.index} / ${t.max}`;
        }

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
          const panel = ensureAgentPanel();
          const step = document.createElement('div');
          step.className = 'agent-step running';
          step.dataset.callId = t.call_id || '';
          step.innerHTML = `
            <div class="agent-step-head">
              <span class="agent-step-dot"></span>
              <span class="agent-step-name">${escHtml(t.name || 'tool')}</span>
              <span class="agent-step-status">running</span>
            </div>
            <pre class="agent-step-args">${escHtml(JSON.stringify(t.args || {}, null, 2))}</pre>
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
          hadEdits = true;
          const step = toolEls.get(t.call_id);
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
              <div class="agent-perm-msg">approve <b>${escHtml(t.name)}</b>?</div>
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

        if (chunk.tool_result) {
          const t = chunk.tool_result;
          const step = toolEls.get(t.call_id);
          if (step) {
            step.classList.remove('running');
            step.classList.toggle('error', !!t.error);
            const status = step.querySelector('.agent-step-status');
            if (status) status.textContent = t.error ? 'error' : 'done';
            const out = step.querySelector('.agent-step-output');
            if (out && !out.textContent) out.textContent = t.output || '(no output)';
          }
          scrollDown();
        }

        if (chunk.thinking) {
          accThink += chunk.thinking;
          if (!thinkingEl) {
            thinkStart = Date.now();
            thinkingEl = document.createElement('details');
            thinkingEl.className = 'thinking-block thinking-live';
            thinkingEl.open = true;
            thinkingEl.innerHTML = '<summary><span class="think-label">thinking</span><span class="think-timer"></span></summary><div class="thinking-content"></div>';
            body.insertBefore(thinkingEl, body.firstChild);
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
          if (!genStart) { genStart = Date.now(); hideConnBanner(); }  // a real token = we're connected, clear any stale warning
          accText += chunk.delta;
          scheduleRender();
        }
      }
    }

  } catch (e) {
    if (e.name !== 'AbortError') {
      body.innerHTML += `<div class="error-msg">stream error: ${escHtml(e.message)}</div>`;
      if (isConnError(e.message)) showConnBanner(e.message);
    }
  } finally {
    if (renderTimer) { clearTimeout(renderTimer); renderTimer = 0; }
    finishThinking();   // freeze timer even if the reply was thinking-only
    updateStats(true);  // final token count + tok/s (real if usage was sent)
    cursor?.remove();
    body.classList.add('done');

    // revert control — only if the agent actually edited files this run
    if (agentEl && runId && hadEdits) {
      const sum = agentEl.querySelector('summary');
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

    // action buttons
    const wrap = body.parentElement;
    if (wrap && (cleanText || artifacts.length)) {
      const actions = document.createElement('div');
      actions.className = 'msg-actions';
      let html = '';
      if (cleanText) html += `<button class="act-btn" onclick="copyMsg(this)">copy</button>`;
      if (artifacts.length) {
        wrap.dataset.artifacts = JSON.stringify(artifacts);
        html += `<button class="act-btn" onclick="openArtifactFromMsg(this)">open artifact</button>`;
      }
      actions.innerHTML = html;
      wrap.appendChild(actions);
    }

    // auto-open the first artifact
    if (artifacts.length) {
      const a = artifacts[0];
      openArtifact(a.content, a.type, a.title, a.lang);
    }

    setStreaming(false);
    scrollDown();

    // name the chat from its first message (async; updates the sidebar when ready)
    if (freshSession && !isIncognitoMode() && cleanText) {
      fetch(`/api/sessions/${sessionId}/auto-name`, { method: 'POST' })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d?.name) updateSessionName(sessionId, d.name); })
        .catch(() => {});
    }
  }

  function ensureAgentPanel() {
    if (agentEl) return agentEl.querySelector('.agent-step-list');
    agentEl = document.createElement('details');
    agentEl.className = 'agent-steps';
    agentEl.open = true;
    agentEl.innerHTML = '<summary>agent steps</summary><div class="agent-step-list"></div>';
    body.insertBefore(agentEl, body.firstChild);
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
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// connect-type failures (vs a real HTTP error from the provider) → worth the banner
function isConnError(msg = '') {
  return /can'?t connect|connect\s?error|connection (refused|error|reset|timed ?out|aborted)|failed to (establish|connect)|ECONNREFUSED|ENOTFOUND|getaddrinfo|name resolution|cooling down|network is unreachable|read ?timed ?out/i.test(String(msg));
}

function showConnBanner(detail = '') {
  const b = document.getElementById('conn-banner');
  const m = document.getElementById('conn-banner-msg');
  if (!b || !m) return;
  m.innerHTML = `<b>can't reach the model endpoint.</b> the request couldn't connect outbound — `
    + `if you launched aide from a sandboxed shell, restart it from your own terminal `
    + `(<code>python cli.py restart</code>) so it has network.`
    + (detail ? ` <span style="opacity:.7">— ${escHtml(String(detail).slice(0, 160))}</span>` : '');
  b.style.display = 'flex';
}

export function hideConnBanner() {
  const b = document.getElementById('conn-banner');
  if (b) b.style.display = 'none';
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

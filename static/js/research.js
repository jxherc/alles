import { mdToHtml } from './util.js';
import { getActiveId, showMessages, scrollDown } from './sessions.js';

let _active = false;
let _sessionId = null;

export function isResearchMode() { return _active; }

export function setResearchMode(on) {
  _active = on;
  const btn = document.getElementById('research-mode-btn');
  if (btn) btn.classList.toggle('active', on);
}


export async function runResearch(query) {
  const sid = getActiveId();
  if (!sid) return;
  _sessionId = sid;

  showMessages();
  const container = document.getElementById('messages');

  // user query row
  const userRow = document.createElement('div');
  userRow.className = 'msg-row';
  userRow.innerHTML = `<div class="user-wrap"><div class="user-bubble">${escHtml(query)}</div></div>`;
  container.appendChild(userRow);

  // research progress card
  const resRow = document.createElement('div');
  resRow.className = 'msg-row';
  resRow.innerHTML = `
    <div class="research-card" id="research-card-${sid}">
      <div class="research-header">
        <span class="research-label">
          <span class="live-dot" id="research-dot"></span>
          researching
        </span>
        <button class="act-btn" id="research-cancel-btn">cancel</button>
      </div>
      <div class="research-steps" id="research-steps"></div>
      <div class="research-report" id="research-report" style="display:none"></div>
      <div class="research-sources" id="research-sources" style="display:none"></div>
    </div>`;
  container.appendChild(resRow);
  scrollDown();

  const stepsEl  = document.getElementById('research-steps');
  const reportEl = document.getElementById('research-report');
  const sourcesEl = document.getElementById('research-sources');
  const dot      = document.getElementById('research-dot');

  document.getElementById('research-cancel-btn').addEventListener('click', () => {
    fetch(`/api/research/${sid}/cancel`, { method: 'POST' }).catch(() => {});
  });

  let reportAccum = '';

  try {
    const r = await fetch('/api/research', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query, session_id: sid }),
    });

    if (!r.ok) {
      stepsEl.innerHTML += `<div class="research-step error">${escHtml(await r.text())}</div>`;
      return;
    }

    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });

      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        const raw = line.slice(5).trim();
        if (raw === '[DONE]') break;
        let ev;
        try { ev = JSON.parse(raw); } catch { continue; }

        if (ev.type === 'step') {
          const s = document.createElement('div');
          s.className = 'research-step';
          s.textContent = ev.text;
          stepsEl.appendChild(s);
          scrollDown();
        }

        if (ev.type === 'finding') {
          const s = document.createElement('div');
          s.className = 'research-finding';
          s.textContent = '→ ' + ev.text;
          stepsEl.appendChild(s);
          scrollDown();
        }

        if (ev.type === 'report_delta') {
          reportAccum += ev.text;
          reportEl.style.display = 'block';
          reportEl.innerHTML = mdToHtml(reportAccum);
          scrollDown();
        }

        if (ev.type === 'done') {
          dot.style.animation = 'none';
          dot.style.opacity = '0.4';
          document.getElementById('research-cancel-btn').style.display = 'none';
          reportEl.style.display = 'block';
          reportEl.innerHTML = mdToHtml(ev.report || reportAccum);

          if (ev.sources?.length) {
            sourcesEl.style.display = 'block';
            sourcesEl.innerHTML = '<div class="sources-label">sources</div>' +
              ev.sources.map(s =>
                `<a class="source-link" href="${s.url}" target="_blank" rel="noopener">${s.title || s.url}</a>`
              ).join('');
          }
          scrollDown();
        }

        if (ev.type === 'error') {
          stepsEl.innerHTML += `<div class="research-step error">error: ${escHtml(ev.text)}</div>`;
        }
      }
    }
  } catch (e) {
    stepsEl.innerHTML += `<div class="research-step error">${escHtml(e.message)}</div>`;
  }
}


function escHtml(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

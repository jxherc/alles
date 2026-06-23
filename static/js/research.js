import { mdToHtml } from './util.js';
import { ensureSession, showMessages, scrollDown } from './sessions.js';

let _active = false;
let _sessionId = null;

export function isResearchMode() { return _active; }

export function setResearchMode(on) {
  _active = on;
  const btn = document.getElementById('research-toggle-btn');
  if (btn) btn.classList.toggle('active', on);
}


export async function runResearch(query) {
  const sid = await ensureSession();   // create a session on a fresh chat so research can run
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
    <div class="research-card">
      <div class="research-header">
        <span class="research-label">
          <span class="live-dot rs-dot"></span>
          researching
        </span>
        <button class="act-btn rs-cancel">cancel</button>
      </div>
      <div class="research-steps rs-steps"><div class="research-step rs-warming">searching the web…</div></div>
      <div class="research-report rs-report" style="display:none"></div>
      <div class="research-stats rs-stats" style="display:none"></div>
      <div class="research-sources rs-sources" style="display:none"></div>
    </div>`;
  container.appendChild(resRow);
  scrollDown();

  // scope every ref to THIS card (classes, not shared ids — a 2nd query must not write
  // into the 1st card). a warming line keeps the card from looking blank while we wait.
  const stepsEl   = resRow.querySelector('.rs-steps');
  const reportEl  = resRow.querySelector('.rs-report');
  const statsEl   = resRow.querySelector('.rs-stats');
  const sourcesEl = resRow.querySelector('.rs-sources');
  const dot       = resRow.querySelector('.rs-dot');
  const cancelBtn = resRow.querySelector('.rs-cancel');
  const clearWarming = () => resRow.querySelector('.rs-warming')?.remove();

  let cancelled = false;
  cancelBtn.addEventListener('click', () => {
    if (cancelled) return;
    cancelled = true;
    fetch(`/api/research/${sid}/cancel`, { method: 'POST' }).catch(() => {});
    cancelBtn.disabled = true;
    cancelBtn.textContent = 'cancelling…';
    dot.style.animation = 'none';
    dot.style.opacity = '0.4';
    clearWarming();
    const s = document.createElement('div');
    s.className = 'research-step';
    s.textContent = 'cancelling… (finishing the current report)';
    stepsEl.appendChild(s);
    scrollDown();
  });

  let reportAccum = '';
  const seenSources = new Set();   // live sources discovered as we read pages

  const addSource = (url, title) => {
    if (!url || seenSources.has(url)) return;
    seenSources.add(url);
    sourcesEl.style.display = 'block';
    if (!sourcesEl.querySelector('.sources-label'))
      sourcesEl.innerHTML = '<div class="sources-label">sources</div>';
    const a = document.createElement('a');
    a.className = 'source-link';
    a.href = url; a.target = '_blank'; a.rel = 'noopener';
    a.textContent = title || url;
    sourcesEl.appendChild(a);
  };

  try {
    const r = await fetch('/api/research', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query, session_id: sid }),
    });

    if (!r.ok) {
      clearWarming();
      dot.style.animation = 'none'; dot.style.opacity = '0.4';
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
          clearWarming();
          const s = document.createElement('div');
          s.className = 'research-step';
          s.textContent = ev.text;
          stepsEl.appendChild(s);
          scrollDown();
        }

        // live source discovery (new engine streams these as it reads pages)
        else if (ev.type === 'source') {
          addSource(ev.url, ev.title);
          scrollDown();
        }

        // kept for back-compat with the old engine's streamed shapes
        else if (ev.type === 'finding') {
          clearWarming();
          const s = document.createElement('div');
          s.className = 'research-finding';
          s.textContent = '→ ' + ev.text;
          stepsEl.appendChild(s);
          scrollDown();
        }
        else if (ev.type === 'report_delta') {
          clearWarming();
          reportAccum += ev.text;
          reportEl.style.display = 'block';
          reportEl.innerHTML = mdToHtml(reportAccum);
          scrollDown();
        }

        else if (ev.type === 'done') {
          clearWarming();
          dot.style.animation = 'none';
          dot.style.opacity = '0.4';
          cancelBtn.style.display = 'none';
          reportEl.style.display = 'block';
          const finalReport = (ev.report || reportAccum).trim();
          reportEl.innerHTML = finalReport
            ? mdToHtml(finalReport)
            : '<div class="research-step">no results — try rephrasing your question.</div>';

          if (ev.stats && Object.keys(ev.stats).length) {
            statsEl.style.display = 'block';
            statsEl.innerHTML = Object.entries(ev.stats)
              .map(([k, v]) => `<span class="research-stat"><b>${escHtml(k)}</b> ${escHtml(String(v))}</span>`)
              .join('');
          }

          // final dedup'd source list (overwrites the live one)
          if (ev.sources?.length) {
            sourcesEl.style.display = 'block';
            sourcesEl.innerHTML = '<div class="sources-label">sources</div>';
            for (const s of ev.sources) {
              const a = document.createElement('a');
              a.className = 'source-link';
              a.href = s.url; a.target = '_blank'; a.rel = 'noopener';
              a.textContent = s.title || s.url;
              sourcesEl.appendChild(a);
            }
          }
          scrollDown();
        }

        else if (ev.type === 'error') {
          stepsEl.innerHTML += `<div class="research-step error">error: ${escHtml(ev.text)}</div>`;
        }
      }
    }
  } catch (e) {
    clearWarming();
    dot.style.animation = 'none'; dot.style.opacity = '0.4';
    stepsEl.innerHTML += `<div class="research-step error">${escHtml(e.message)}</div>`;
  }
}


function escHtml(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

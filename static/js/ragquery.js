// chat-with-your-docs (RAG) — a composer mode like research: ask a question,
// get an answer grounded in your vault docs with the source files cited.
import { mdToHtml } from './util.js';
import { getActiveId, showMessages, scrollDown } from './sessions.js';

let _active = false;
export function isDocsMode() { return _active; }
export function setDocsMode(on) {
  _active = on;
  document.getElementById('docs-toggle-btn')?.classList.toggle('active', on);
}

export async function runDocsQuery(query) {
  const sid = getActiveId();
  if (!sid) return;
  showMessages();
  const container = document.getElementById('messages');

  const userRow = document.createElement('div');
  userRow.className = 'msg-row';
  userRow.innerHTML = `<div class="user-wrap"><div class="user-bubble">${esc(query)}</div></div>`;
  container.appendChild(userRow);

  const row = document.createElement('div');
  row.className = 'msg-row';
  row.innerHTML = `<div class="research-card">
    <div class="research-header"><span class="research-label"><span class="live-dot" id="docs-dot"></span> searching your docs</span></div>
    <div class="research-report" id="docs-ans">…</div>
    <div class="research-sources" id="docs-src" style="display:none"></div>
  </div>`;
  container.appendChild(row);
  scrollDown();

  try {
    const r = await fetch('/api/rag/ask', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query }),
    });
    const d = await r.json();
    const dot = document.getElementById('docs-dot');
    if (dot) { dot.style.animation = 'none'; dot.style.opacity = '0.4'; }
    if (!r.ok) { document.getElementById('docs-ans').textContent = d.detail || 'failed'; return; }
    document.getElementById('docs-ans').innerHTML = mdToHtml(d.answer || '');
    if (d.sources?.length) {
      const s = document.getElementById('docs-src');
      s.style.display = 'block';
      s.innerHTML = '<div class="sources-label">from your docs</div>' +
        d.sources.map(p => `<span class="source-link">${esc(p)}</span>`).join('');
    }
    scrollDown();
  } catch (e) {
    document.getElementById('docs-ans').textContent = e.message || 'failed';
  }
}

function esc(s = '') { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

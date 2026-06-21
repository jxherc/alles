// watch — uptime / status dashboard for EXTERNAL things (sites, /health endpoints,
// TLS certs). polls /api/watch/overview live; the AI-cost card just reads the usage
// summary aide already tracks. hand-drawn SVG sparklines, no chart lib. distinct from
// the `system` app (which watches this machine).
import { toast } from './util.js';
import { initCustomDropdown } from './dropdown.js';
import { confirm as dlgConfirm } from './dialog.js';
const _si = n => (window.icon ? window.icon(n) : '');

const $ = id => document.getElementById(id);
let _mons = [];
let _ai = null;
let _editing = null;
let _adding = false;
let _poll = null;

export function initWatch() {
  loadWatch();
  _startPoll();
  document.addEventListener('visibilitychange', _onVis);
}

function _onVis() {
  if (document.hidden) { _stopPoll(); }
  else { loadWatch(); _startPoll(); }
}
function _startPoll() { _stopPoll(); _poll = setInterval(() => { if (!document.hidden) _refreshQuiet(); }, 15000); }
function _stopPoll() { if (_poll) { clearInterval(_poll); _poll = null; } }

export async function loadWatch() {
  try {
    _mons = (await fetch('/api/watch/overview').then(r => r.json())).monitors || [];
  } catch { _mons = []; }
  try {
    _ai = await fetch('/api/usage/summary').then(r => r.json());
  } catch { _ai = null; }
  _render();
}

// a quiet refresh that doesn't blow away an open add/edit form
async function _refreshQuiet() {
  if (_editing || _adding) return;
  await loadWatch();
}

// ── helpers ───────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _statusDot(s) {
  return `<span class="watch-dot ${s}" title="${s}"></span>`;
}

function _agoLabel(iso) {
  if (!iso) return 'never';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function _spark(vals) {
  if (!vals || vals.length < 2) return '<span class="watch-spark-empty">—</span>';
  const w = 90, h = 22, max = Math.max(...vals, 1);
  const pts = vals.map((v, i) =>
    `${((i / (vals.length - 1)) * w).toFixed(1)},${(h - (v / max) * (h - 2) - 1).toFixed(1)}`
  ).join(' ');
  return `<svg class="watch-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts}"/></svg>`;
}

function _uptimeStr(p) { return p == null ? '—' : `${p}%`; }

// cert monitors have no latency to plot — show a depleting time-to-expiry bar instead
function _certBar(m) {
  const raw = m.latest && m.latest.detail ? parseInt(m.latest.detail, 10) : NaN;
  if (Number.isNaN(raw)) return '<span class="watch-spark-empty">—</span>';
  const pct = Math.max(2, Math.min(100, (raw / 90) * 100));   // 90-day horizon
  const cls = raw < 14 ? 'crit' : raw < 30 ? 'warn' : 'ok';
  return `<div class="watch-cert-bar ${cls}" title="${raw} days until certificate expiry"><i style="width:${pct}%"></i></div>`;
}

function _kindBadge(k) {
  const ic = { http: 'eye', health: 'check', cert: 'shield' }[k] || 'eye';
  return `<span class="watch-kind">${_si(ic)}${k}</span>`;
}

// ── render ──────────────────────────────────────────────────────────────────
function _render() {
  const body = $('watch-body');
  if (!body) return;

  const up = _mons.filter(m => m.status === 'up').length;
  const down = _mons.filter(m => m.status === 'down').length;
  const unk = _mons.filter(m => m.status === 'unknown').length;
  const sumBits = [];
  if (up) sumBits.push(`${up} up`);
  if (down) sumBits.push(`${down} down`);
  if (unk) sumBits.push(`${unk} pending`);

  const cards = _mons.map(m => m.id === _editing ? _editCard(m) : _card(m)).join('');
  const grid = _mons.length
    ? `<div class="watch-grid">${cards}</div>`
    : (_adding ? '' : `<div class="watch-empty">nothing watched yet — add a site, a <code>/health</code> endpoint, or a cert to keep an eye on. add one below.</div>`);

  body.innerHTML = `
    <div class="watch-bar">
      <div class="watch-summary">${sumBits.join(' · ') || 'no monitors'}</div>
      <div class="watch-bar-actions">
        <button class="btn" id="watch-refresh-all">${_si('refresh')} refresh all</button>
        <button class="btn primary" id="watch-add-toggle">${_si('plus')} monitor</button>
      </div>
    </div>
    ${_aiCard()}
    ${_adding ? _addForm() : ''}
    ${grid}
  `;
  _wire(body);
}

function _aiCard() {
  if (!_ai) return '';
  const fmt = n => (n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(n || 0));
  const months = _ai.by_month || [];
  const thisMonth = months.length ? months[months.length - 1] : null;
  const top = (_ai.by_model || []).slice(0, 3);
  return `
    <div class="watch-ai">
      <div class="watch-ai-head">${_si('activity')} ai usage</div>
      <div class="watch-ai-stats">
        <div class="watch-ai-stat"><b>${fmt(_ai.total_tokens || 0)}</b><span>total tokens</span></div>
        <div class="watch-ai-stat"><b>${fmt(thisMonth ? thisMonth.total : 0)}</b><span>this month</span></div>
        <div class="watch-ai-stat"><b>${(_ai.total_messages || 0).toLocaleString()}</b><span>messages</span></div>
      </div>
      ${top.length ? `<div class="watch-ai-models">${top.map(m => `<span title="${esc(m.name)}: ${m.total.toLocaleString()} tok">${esc(m.name)} · ${fmt(m.total)}</span>`).join('')}</div>` : ''}
    </div>`;
}

function _card(m) {
  const l = m.latest;
  const latency = l && l.latency_ms ? `${l.latency_ms}ms` : '';
  const detail = l && l.detail ? l.detail : '';
  const errLine = m.status === 'down' && l && l.error ? `<div class="watch-err" title="${esc(l.error)}">${esc(l.error)}</div>` : '';
  return `
    <div class="watch-card ${m.status}" data-id="${m.id}">
      <div class="watch-card-top">
        ${_statusDot(m.status)}
        <div class="watch-name">${esc(m.name)}</div>
        ${_kindBadge(m.kind)}
      </div>
      <div class="watch-url" title="${esc(m.url)}">${esc(m.url)}</div>
      <div class="watch-spark-row">${m.kind === 'cert' ? _certBar(m) : _spark(m.spark)}</div>
      <div class="watch-stats">
        <span>${m.kind === 'cert' && detail ? detail + ' left' : (latency || '—')}</span>
        <span title="uptime, last 24h / 7d">${_uptimeStr(m.uptime_24h)} <i>/</i> ${_uptimeStr(m.uptime_7d)}</span>
        <span class="watch-ago">${l ? _agoLabel(l.ts) : 'never'}</span>
      </div>
      ${errLine}
      <div class="watch-actions">
        <button class="icon-btn" data-act="check" title="check now">${_si('refresh')}</button>
        <button class="icon-btn" data-act="edit" title="edit">${_si('edit')}</button>
        <button class="icon-btn danger" data-act="del" title="delete">${_si('trash')}</button>
      </div>
    </div>`;
}

function _kindSelect(val) {
  return `<div class="settings-input custom-select" data-f="kind" data-value="${esc(val || 'http')}" data-options="http|http (site is up);health|health (json/keyword);cert|cert (tls expiry)"></div>`;
}

function _editCard(m) {
  return `
    <div class="watch-card editing" data-id="${m.id}">
      <input type="text" class="settings-input" data-f="name" value="${esc(m.name)}" placeholder="name">
      <input type="text" class="settings-input" data-f="url" value="${esc(m.url)}" placeholder="https://example.com">
      ${_kindSelect(m.kind)}
      <div class="watch-edit-row">
        <input type="text" class="settings-input" data-f="interval_secs" value="${m.interval_secs}" inputmode="numeric" placeholder="interval (s)" title="seconds between checks">
        <input type="text" class="settings-input" data-f="expect_status" value="${m.expect_status}" inputmode="numeric" placeholder="status (0=any 2xx)" title="required status code, 0 = accept any 2xx/3xx">
      </div>
      <div class="watch-edit-row">
        <input type="text" class="settings-input" data-f="expect_keyword" value="${esc(m.expect_keyword)}" placeholder="keyword in body" title="text that must appear in the response">
        <input type="text" class="settings-input" data-f="latency_ceiling_ms" value="${m.latency_ceiling_ms}" inputmode="numeric" placeholder="max ms (0=off)" title="fail if slower than this (ms), 0 = no ceiling">
      </div>
      <div class="watch-actions">
        <button class="btn primary" data-act="save">save</button>
        <button class="btn" data-act="cancel">cancel</button>
      </div>
    </div>`;
}

function _addForm() {
  return `
    <div class="watch-card editing watch-add" data-add="1">
      <input type="text" class="settings-input" data-f="name" placeholder="name (e.g. my site)">
      <input type="text" class="settings-input" data-f="url" placeholder="https://example.com">
      ${_kindSelect('http')}
      <div class="watch-edit-row">
        <input type="text" class="settings-input" data-f="interval_secs" value="300" inputmode="numeric" placeholder="interval (s)">
        <input type="text" class="settings-input" data-f="expect_keyword" placeholder="keyword (optional)">
      </div>
      <div class="watch-actions">
        <button class="btn primary" data-act="create">add monitor</button>
        <button class="btn" data-act="cancel-add">cancel</button>
      </div>
    </div>`;
}

// ── wiring ──────────────────────────────────────────────────────────────────
function _wire(body) {
  body.querySelectorAll('.custom-select').forEach(initCustomDropdown);

  $('watch-refresh-all')?.addEventListener('click', _checkAll);
  $('watch-add-toggle')?.addEventListener('click', () => { _adding = !_adding; _editing = null; _render(); });

  // add form
  const addCard = body.querySelector('.watch-add');
  if (addCard) {
    addCard.querySelector('[data-act="create"]')?.addEventListener('click', () => _create(addCard));
    addCard.querySelector('[data-act="cancel-add"]')?.addEventListener('click', () => { _adding = false; _render(); });
  }

  body.querySelectorAll('.watch-card[data-id]').forEach(card => {
    const id = card.dataset.id;
    card.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', async () => {
      const act = btn.dataset.act;
      if (act === 'edit') { _editing = id; _adding = false; _render(); return; }
      if (act === 'cancel') { _editing = null; _render(); return; }
      if (act === 'check') {
        btn.classList.add('spinning');
        await fetch(`/api/watch/${id}/check`, { method: 'POST' });
        await loadWatch();
        return;
      }
      if (act === 'del') {
        const m = _mons.find(x => x.id === id);
        if (!await dlgConfirm(`stop watching ${m?.name || 'this'}?`)) return;
        await fetch(`/api/watch/${id}`, { method: 'DELETE' });
        toast('removed', 'success');
        loadWatch();
        return;
      }
      if (act === 'save') {
        const v = f => card.querySelector(`[data-f="${f}"]`);
        const num = f => { const n = parseInt(v(f)?.value, 10); return Number.isNaN(n) ? undefined : n; };
        const r = await fetch(`/api/watch/${id}`, {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            name: v('name')?.value.trim(), url: v('url')?.value.trim(),
            kind: v('kind')?.dataset.value, interval_secs: num('interval_secs'),
            expect_status: num('expect_status'), expect_keyword: v('expect_keyword')?.value.trim(),
            latency_ceiling_ms: num('latency_ceiling_ms'),
          }),
        });
        if (!r.ok) { toast((await r.json()).detail || 'save failed', 'error'); return; }
        _editing = null;
        toast('saved', 'success');
        loadWatch();
        return;
      }
    }));
  });
}

async function _create(card) {
  const v = f => card.querySelector(`[data-f="${f}"]`);
  const name = v('name')?.value.trim();
  const url = v('url')?.value.trim();
  if (!name) { toast('give it a name', 'error'); return; }
  if (!url) { toast('what url should i watch?', 'error'); return; }
  const interval = parseInt(v('interval_secs')?.value, 10);
  const r = await fetch('/api/watch', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      name, url, kind: v('kind')?.dataset.value || 'http',
      interval_secs: Number.isNaN(interval) ? 300 : interval,
      expect_keyword: v('expect_keyword')?.value.trim() || '',
    }),
  });
  if (!r.ok) { toast((await r.json()).detail || 'failed to add', 'error'); return; }
  _adding = false;
  toast(`watching ${name}`, 'success');
  // probe it once right away so the card isn't stuck on "pending"
  try { const m = await r.json(); fetch(`/api/watch/${m.id}/check`, { method: 'POST' }).then(() => loadWatch()); } catch { /* ignore */ }
  loadWatch();
}

async function _checkAll() {
  const btn = $('watch-refresh-all');
  btn?.classList.add('spinning');
  await Promise.all(_mons.map(m => fetch(`/api/watch/${m.id}/check`, { method: 'POST' }).catch(() => {})));
  await loadWatch();
}

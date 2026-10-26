// watch — uptime / status dashboard for EXTERNAL things (sites, /health endpoints,
// TLS certs). polls /api/watch/overview live; the AI-cost card just reads the usage
// summary aide already tracks. hand-drawn SVG sparklines, no chart lib. distinct from
// the `system` app (which watches this machine).
import { toast } from './util.js';
import { initCustomDropdown } from './dropdown.js?v=213';
import { confirm as dlgConfirm } from './dialog.js';
import { formatNumber, t, tp } from './i18n.js';
const _si = n => (window.icon ? window.icon(n) : '');

const $ = id => document.getElementById(id);
let _mons = [];
let _ai = null;
let _statusCfg = { enabled: false };
let _editing = null;
let _adding = false;
let _poll = null;
let _loadSequence = 0;
let _loadError = '';
let _statusError = '';
let _statusLoaded = false;
let _statusPending = false;
const _deleting = new Set();

export function initWatch(fetcher = fetch) {
  const loading = loadWatch(fetcher);
  _startPoll();
  document.addEventListener('visibilitychange', _onVis);
  return loading;
}

function _onVis() {
  if (document.hidden) { _stopPoll(); }
  else { loadWatch(); _startPoll(); }
}
function _startPoll() { _stopPoll(); _poll = setInterval(() => { if (document.hidden || document.getElementById('watch-view')?.style.display === 'none') return; _refreshQuiet(); }, 15000); }
function _stopPoll() { if (_poll) { clearInterval(_poll); _poll = null; } }

export async function loadWatch(fetcher = fetch) {
  const sequence = ++_loadSequence;
  const [monitors, usage, status] = await Promise.allSettled([
    watchJson(fetcher, '/api/watch/overview', undefined, value => Array.isArray(value?.monitors)
      && value.monitors.every(item => item && typeof item.id === 'string' && typeof item.name === 'string')),
    watchJson(fetcher, '/api/usage/summary'),
    watchJson(fetcher, '/api/status/config', undefined, value => typeof value?.enabled === 'boolean'),
  ]);
  if (sequence !== _loadSequence) return;
  _loadError = monitors.status === 'rejected' ? monitors.reason.message : '';
  if (monitors.status === 'fulfilled') _mons = monitors.value.monitors;
  _ai = usage.status === 'fulfilled' ? usage.value : null;
  _statusError = status.status === 'rejected' ? status.reason.message : '';
  _statusLoaded = status.status === 'fulfilled';
  if (_statusLoaded) _statusCfg = status.value;
  _render();
}

async function watchJson(request, path, options, valid = value => value && typeof value === 'object') {
  const response = await request(path, options);
  const value = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof value?.detail === 'string' ? value.detail : t('server.watch_request_failed', { status: response.status }));
  if (!valid(value)) throw new Error(t('common.response_unconfirmed'));
  return value;
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
  return `<span class="watch-dot ${s}" title="${esc(['up', 'down'].includes(s) ? t(`server.watch_status_${s}`) : t('common.unknown'))}"></span>`;
}

function _agoLabel(iso) {
  if (!iso) return t('server.watch_never');
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return '';
  const s = Math.max(0, Math.round((Date.now() - at) / 1000));
  if (s < 60) return t('server.ago_seconds', { count: s });
  if (s < 3600) return t('server.ago_minutes', { count: Math.round(s / 60) });
  if (s < 86400) return t('server.ago_hours', { count: Math.round(s / 3600) });
  return t('server.ago_days', { count: Math.round(s / 86400) });
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
  return `<div class="watch-cert-bar ${cls}" title="${esc(tp('server.watch_cert_days', raw))}"><i style="width:${pct}%"></i></div>`;
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
  if (up) sumBits.push(t('server.watch_n_up', { count: up }));
  if (down) sumBits.push(t('server.watch_n_down', { count: down }));
  if (unk) sumBits.push(t('server.watch_n_pending', { count: unk }));

  const cards = _mons.map(m => m.id === _editing ? _editCard(m) : _card(m)).join('');
  const grid = _mons.length
    ? `<div class="watch-grid">${cards}</div>`
    : (_adding || _loadError ? '' : `<div class="watch-empty">${esc(t('server.watch_empty'))}</div>`);

  body.innerHTML = `
    <div class="watch-bar">
      <div class="watch-summary">${_loadError ? esc(_mons.length ? t('server.watch_last_loaded') : t('server.watch_unavailable')) : esc(sumBits.join(' · ') || t('server.watch_no_monitors'))}</div>
      <div class="watch-bar-actions">
        ${_statusCfg.enabled ? `<a class="btn" href="/status" target="_blank" rel="noopener" title="${esc(t('server.watch_status_page_title'))}">${esc(t('server.watch_status_page'))} ${_si('external')}</a>` : ''}
        <button type="button" class="btn" id="watch-status-toggle" aria-pressed="${!!_statusCfg.enabled}" title="${esc(t('server.watch_toggle_title'))}"${_statusPending || !_statusLoaded ? ' disabled' : ''}${_statusPending ? ' aria-busy="true"' : ''}>${esc(t('server.watch_status_line', { state: _statusLoaded ? (_statusCfg.enabled ? t('server.watch_public') : t('server.watch_off')) : t('common.unavailable') }))}</button>
        <button class="btn" id="watch-refresh-all">${_si('refresh')} ${esc(t('server.watch_refresh_all'))}</button>
        <button class="btn primary" id="watch-add-toggle">${_si('plus')} ${esc(t('server.watch_monitor'))}</button>
      </div>
    </div>
    ${_loadError || _statusError ? `<div class="watch-empty" role="alert">${_loadError ? esc(t('server.watch_load_failed', { reason: _loadError })) : ''}${_statusError ? `<div>${esc(t('server.watch_status_read_failed', { reason: _statusError }))}</div>` : ''} <button class="btn" id="watch-retry">${esc(t('common.retry'))}</button></div>` : ''}
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
      <div class="watch-ai-head">${_si('activity')} ${esc(t('server.watch_ai_usage'))}</div>
      <div class="watch-ai-stats">
        <div class="watch-ai-stat"><b>${fmt(_ai.total_tokens || 0)}</b><span>${esc(t('server.watch_total_tokens'))}</span></div>
        <div class="watch-ai-stat"><b>${fmt(thisMonth ? thisMonth.total : 0)}</b><span>${esc(t('server.watch_this_month'))}</span></div>
        <div class="watch-ai-stat"><b>${formatNumber(_ai.total_messages || 0)}</b><span>${esc(t('server.watch_messages'))}</span></div>
      </div>
      ${top.length ? `<div class="watch-ai-models">${top.map(m => `<span title="${esc(t('server.watch_tok', { name: m.name, count: formatNumber(m.total) }))}">${esc(m.name)} · ${fmt(m.total)}</span>`).join('')}</div>` : ''}
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
        <span>${m.kind === 'cert' && detail ? t('server.watch_left', { detail }) : (latency || '—')}</span>
        <span title="${esc(t('server.watch_uptime_title'))}">${_uptimeStr(m.uptime_24h)} <i>/</i> ${_uptimeStr(m.uptime_7d)}</span>
        <span class="watch-ago">${l ? _agoLabel(l.ts) : esc(t('server.watch_never'))}</span>
      </div>
      ${errLine}
      <div class="watch-actions">
        <button class="icon-btn" data-act="check" title="${esc(t('server.watch_check_now'))}">${_si('refresh')}</button>
        <button class="icon-btn" data-act="edit" title="${esc(t('common.edit'))}">${_si('edit')}</button>
        <button class="icon-btn danger" data-act="del" title="${esc(t('common.delete'))}"${_deleting.has(m.id) ? ' disabled aria-busy="true"' : ''}>${_si('trash')}</button>
      </div>
    </div>`;
}

function _kindSelect(val) {
  return `<div class="settings-input custom-select" data-f="kind" data-value="${esc(val || 'http')}" data-options="${esc(`http|${t('server.watch_kind_http')};health|${t('server.watch_kind_health')};cert|${t('server.watch_kind_cert')}`)}"></div>`;
}

function _editCard(m) {
  return `
    <div class="watch-card editing" data-id="${m.id}">
      <input type="text" class="settings-input" data-f="name" value="${esc(m.name)}" placeholder="${esc(t('server.watch_name'))}">
      <input type="text" class="settings-input" data-f="url" value="${esc(m.url)}" placeholder="https://example.com">
      ${_kindSelect(m.kind)}
      <div class="watch-edit-row">
        <input type="text" class="settings-input" data-f="interval_secs" value="${m.interval_secs}" inputmode="numeric" placeholder="${esc(t('server.watch_interval'))}" title="${esc(t('server.watch_interval_title'))}">
        <input type="text" class="settings-input" data-f="expect_status" value="${m.expect_status}" inputmode="numeric" placeholder="${esc(t('server.watch_status_ph'))}" title="${esc(t('server.watch_status_title'))}">
      </div>
      <div class="watch-edit-row">
        <input type="text" class="settings-input" data-f="expect_keyword" value="${esc(m.expect_keyword)}" placeholder="${esc(t('server.watch_keyword_body'))}" title="${esc(t('server.watch_keyword_title'))}">
        <input type="text" class="settings-input" data-f="latency_ceiling_ms" value="${m.latency_ceiling_ms}" inputmode="numeric" placeholder="${esc(t('server.watch_max_ms'))}" title="${esc(t('server.watch_max_ms_title'))}">
      </div>
      <div class="watch-actions">
        <button class="btn primary" data-act="save">${esc(t('common.save'))}</button>
        <button class="btn" data-act="cancel">${esc(t('common.cancel'))}</button>
      </div>
    </div>`;
}

function _addForm() {
  return `
    <div class="watch-card editing watch-add" data-add="1">
      <input type="text" class="settings-input" data-f="name" placeholder="${esc(t('server.watch_name_example'))}">
      <input type="text" class="settings-input" data-f="url" placeholder="https://example.com">
      ${_kindSelect('http')}
      <div class="watch-edit-row">
        <input type="text" class="settings-input" data-f="interval_secs" value="300" inputmode="numeric" placeholder="${esc(t('server.watch_interval'))}">
        <input type="text" class="settings-input" data-f="expect_keyword" placeholder="${esc(t('server.watch_keyword_optional'))}">
      </div>
      <div class="watch-actions">
        <button class="btn primary" data-act="create">${esc(t('server.watch_add_monitor'))}</button>
        <button class="btn" data-act="cancel-add">${esc(t('common.cancel'))}</button>
      </div>
    </div>`;
}

// ── wiring ──────────────────────────────────────────────────────────────────
function _wire(body) {
  body.querySelectorAll('.custom-select').forEach(initCustomDropdown);

  $('watch-refresh-all')?.addEventListener('click', _checkAll);
  $('watch-retry')?.addEventListener('click', async () => {
    const button = $('watch-retry');
    button.disabled = true;
    await loadWatch();
    if (document.activeElement === document.body) ($('watch-retry') || $('watch-add-toggle'))?.focus();
  });
  $('watch-add-toggle')?.addEventListener('click', () => { _adding = !_adding; _editing = null; _render(); });
  $('watch-status-toggle')?.addEventListener('click', async () => {
    if (_statusPending || !_statusLoaded) return;
    const button = $('watch-status-toggle');
    const next = !_statusCfg.enabled;
    _statusPending = true;
    button.disabled = true; button.setAttribute('aria-busy', 'true');
    try {
      const saved = await watchJson(fetch, '/api/status/config', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ enabled: next }) }, value => value?.enabled === next);
      ++_loadSequence;
      _statusCfg = saved;
      if (button.isConnected) {
        toast(next ? t('server.watch_now_public') : t('server.watch_turned_off'), next ? 'success' : 'info');
        _render();
      }
    } catch (error) { toast(error.message || t('server.watch_status_change_failed'), 'error'); }
    finally {
      _statusPending = false;
      const current = $('watch-status-toggle');
      if (current) {
        current.disabled = !_statusLoaded; current.removeAttribute('aria-busy');
        current.textContent = t('server.watch_status_line', { state: _statusLoaded ? (_statusCfg.enabled ? t('server.watch_public') : t('server.watch_off')) : t('common.unavailable') });
        current.setAttribute('aria-pressed', String(!!_statusCfg.enabled));
        if (document.activeElement === document.body) current.focus();
      }
    }
  });

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
        if (_deleting.has(id)) return;
        _deleting.add(id);
        const m = _mons.find(x => x.id === id);
        try {
          if (!await dlgConfirm(m?.name ? t('server.watch_stop', { name: m.name }) : t('server.watch_stop_this'))) return;
          btn.disabled = true; btn.setAttribute('aria-busy', 'true');
          await watchJson(fetch, `/api/watch/${id}`, { method: 'DELETE' }, value => value?.ok === true);
          ++_loadSequence;
          _mons = _mons.filter(item => item.id !== id);
          $('watch-body')?.querySelector(`.watch-card[data-id="${CSS.escape(id)}"]`)?.remove();
          if (_editing === id) _editing = null;
          toast(t('server.watch_removed'), 'success');
          await _refreshQuiet();
          if (document.activeElement === document.body) $('watch-add-toggle')?.focus();
        } catch (error) { toast(error.message || t('server.watch_removal_failed'), 'error'); }
        finally {
          _deleting.delete(id);
          const current = $('watch-body')?.querySelector(`.watch-card[data-id="${CSS.escape(id)}"] [data-act="del"]`) || btn;
          current.disabled = false; current.removeAttribute('aria-busy');
          if (current.isConnected && document.activeElement === document.body) current.focus();
        }
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
        if (!r.ok) { toast((await r.json()).detail || t('server.watch_save_failed'), 'error'); return; }
        _editing = null;
        toast(t('common.saved'), 'success');
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
  if (!name) { toast(t('server.watch_give_name'), 'error'); return; }
  if (!url) { toast(t('server.watch_what_url'), 'error'); return; }
  const interval = parseInt(v('interval_secs')?.value, 10);
  const r = await fetch('/api/watch', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      name, url, kind: v('kind')?.dataset.value || 'http',
      interval_secs: Number.isNaN(interval) ? 300 : interval,
      expect_keyword: v('expect_keyword')?.value.trim() || '',
    }),
  });
  if (!r.ok) { toast((await r.json()).detail || t('server.watch_add_failed'), 'error'); return; }
  _adding = false;
  toast(t('server.watch_watching', { name }), 'success');
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

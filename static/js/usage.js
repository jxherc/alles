// token usage & cost dashboard — reads /api/usage/summary (tokens already saved
// on each assistant message) and shows totals, a by-month bar chart, by-model.
import { t } from './i18n.js';

function fmt(n) {
  return n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(n);
}
function esc(s = '') { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
let loadSequence = 0;

export async function initUsage() {
  const body = document.getElementById('usage-body');
  if (!body) return;
  const sequence = ++loadSequence;
  const totEl = document.getElementById('usage-total');
  if (totEl) totEl.textContent = '';
  body.innerHTML = `<div class="jrnl-empty">${t('aide.loading')}</div>`;
  let d;
  try {
    const response = await fetch('/api/usage/summary');
    if (!response.ok) throw new Error('usage unavailable');
    d = await response.json();
    if (!d || !Array.isArray(d.by_month) || !Array.isArray(d.by_model) ||
        !['total_tokens', 'total_prompt', 'total_completion', 'total_messages'].every(key => Number.isFinite(d[key]) && d[key] >= 0)) {
      throw new Error('bad usage response');
    }
  } catch {
    if (sequence !== loadSequence) return;
    body.innerHTML = `<div class="jrnl-empty" role="status">${t('usage.load_failed')} <button type="button" class="btn" id="usage-retry">${t('common.retry')}</button></div>`;
    document.getElementById('usage-retry')?.addEventListener('click', () => initUsage());
    return;
  }
  if (sequence !== loadSequence) return;

  if (totEl) totEl.textContent = t('usage.total_line', { tokens: fmt(d.total_tokens), messages: d.total_messages });

  if (!d.total_messages) {
    body.innerHTML = `<div class="jrnl-empty">${t('usage.empty')}</div>`;
    return;
  }

  const maxM = Math.max(...d.by_month.map(m => m.total), 1);
  const monthBars = d.by_month.map(m => `
    <div class="subs-bar-row">
      <span class="subs-bar-label">${esc(m.name)}</span>
      <span class="subs-bar-track"><span class="subs-bar-fill" style="width:${(m.total / maxM * 100).toFixed(1)}%"></span></span>
      <span class="subs-bar-val">${fmt(m.total)}</span>
    </div>`).join('');

  const modelRows = d.by_model.map(m => `
    <div class="usage-mrow">
      <span class="usage-mname">${esc(m.name)}</span>
      <span>${t('usage.in', { n: fmt(m.prompt) })}</span>
      <span>${t('usage.out', { n: fmt(m.completion) })}</span>
      <span>${t('usage.msgs', { n: m.messages })}</span>
      <span class="usage-mtotal">${fmt(m.total)}</span>
    </div>`).join('');

  body.innerHTML = `
    <div class="usage-wrap">
      <div class="usage-cards">
        <div class="usage-card"><div class="usage-num">${fmt(d.total_tokens)}</div><div class="usage-lbl">${t('server.watch_total_tokens')}</div></div>
        <div class="usage-card"><div class="usage-num">${fmt(d.total_prompt)}</div><div class="usage-lbl">${t('shell.compare.prompt')}</div></div>
        <div class="usage-card"><div class="usage-num">${fmt(d.total_completion)}</div><div class="usage-lbl">${t('usage.completion')}</div></div>
        <div class="usage-card"><div class="usage-num">${d.total_messages}</div><div class="usage-lbl">${t('aide.brain_messages')}</div></div>
      </div>
      <div class="subs-chart-title" style="margin-top:1.1rem">${t('usage.by_month')}</div>
      ${monthBars}
      <div class="subs-chart-title" style="margin-top:1.1rem">${t('usage.by_model')}</div>
      <div class="usage-models">${modelRows}</div>
    </div>`;
}

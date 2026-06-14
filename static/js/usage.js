// token usage & cost dashboard — reads /api/usage/summary (tokens already saved
// on each assistant message) and shows totals, a by-month bar chart, by-model.

function fmt(n) {
  return n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(n);
}
function esc(s = '') { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

export async function initUsage() {
  const body = document.getElementById('usage-body');
  if (!body) return;
  body.innerHTML = '<div class="jrnl-empty">loading…</div>';
  let d;
  try { d = await fetch('/api/usage/summary').then(r => r.json()); }
  catch { body.innerHTML = '<div class="jrnl-empty">failed to load usage</div>'; return; }

  const totEl = document.getElementById('usage-total');
  if (totEl) totEl.textContent = `${fmt(d.total_tokens)} tokens · ${d.total_messages} messages`;

  if (!d.total_messages) {
    body.innerHTML = '<div class="jrnl-empty">no usage recorded yet — chat with a model and it shows up here</div>';
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
      <span>${fmt(m.prompt)} in</span>
      <span>${fmt(m.completion)} out</span>
      <span>${m.messages} msgs</span>
      <span class="usage-mtotal">${fmt(m.total)}</span>
    </div>`).join('');

  body.innerHTML = `
    <div class="usage-wrap">
      <div class="usage-cards">
        <div class="usage-card"><div class="usage-num">${fmt(d.total_tokens)}</div><div class="usage-lbl">total tokens</div></div>
        <div class="usage-card"><div class="usage-num">${fmt(d.total_prompt)}</div><div class="usage-lbl">prompt</div></div>
        <div class="usage-card"><div class="usage-num">${fmt(d.total_completion)}</div><div class="usage-lbl">completion</div></div>
        <div class="usage-card"><div class="usage-num">${d.total_messages}</div><div class="usage-lbl">messages</div></div>
      </div>
      <div class="subs-chart-title" style="margin-top:1.1rem">tokens by month</div>
      ${monthBars}
      <div class="subs-chart-title" style="margin-top:1.1rem">by model</div>
      <div class="usage-models">${modelRows}</div>
    </div>`;
}

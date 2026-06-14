// subscriptions — recurring costs with billing cycles and renewal reminders
import { toast } from './util.js';
import { initCustomDropdown } from './dropdown.js';
import { initDatePicker } from './datepick.js';
import { confirm as dlgConfirm } from './dialog.js';

const $ = id => document.getElementById(id);
let _subs = [];
let _summary = {};
let _editing = null;   // id of the row currently in edit mode

export async function loadSubs() {
  try {
    const d = await fetch('/api/subscriptions').then(r => r.json());
    _subs = d.subscriptions || [];
    _summary = d.summary || {};
  } catch { _subs = []; _summary = {}; }
  _render();
}

export function initSubsPanel() {
  loadSubs();
  const cycleEl = $('sub-cycle');
  initCustomDropdown(cycleEl);
  initDatePicker($('sub-due'));
  cycleEl?.addEventListener('change', () => {
    $('sub-cycle-days').style.display = cycleEl.dataset.value === 'custom' ? '' : 'none';
  });
  if (!$('sub-add-btn') || $('sub-add-btn').dataset.wired) return;
  $('sub-add-btn').dataset.wired = '1';
  $('sub-add-btn').addEventListener('click', _add);
  $('sub-name')?.addEventListener('keydown', e => { if (e.key === 'Enter') _add(); });
}

async function _add() {
  const name = $('sub-name')?.value.trim();
  const due = $('sub-due')?.value;
  if (!name) { toast('give it a name', 'error'); return; }
  if (!due) { toast('pick the next billing date', 'error'); return; }
  const body = {
    name,
    price: parseFloat($('sub-price')?.value) || 0,
    cycle: $('sub-cycle')?.dataset.value || 'monthly',
    cycle_days: parseInt($('sub-cycle-days')?.value) || 30,
    next_due: due.slice(0, 10),
    category: $('sub-category')?.value.trim() || '',
  };
  const r = await fetch('/api/subscriptions', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) { toast((await r.json()).detail || 'failed to add', 'error'); return; }
  ['sub-name', 'sub-price', 'sub-category', 'sub-cycle-days'].forEach(id => { if ($(id)) $(id).value = ''; });
  toast(`tracking ${name}`, 'success');
  loadSubs();
}

function _dueLabel(s) {
  if (!s.active) return 'paused';
  if (s.days_until < 0) return 'overdue';
  if (s.days_until === 0) return 'today';
  if (s.days_until === 1) return 'tomorrow';
  return `in ${s.days_until}d`;
}

function _cycleLabel(s) {
  if (s.cycle === 'custom') return `every ${s.cycle_days}d`;
  return { weekly: '/wk', monthly: '/mo', quarterly: '/qtr', yearly: '/yr' }[s.cycle] || s.cycle;
}

function _render() {
  const sum = $('subs-summary');
  if (sum) {
    sum.textContent = _summary.active
      ? `${_summary.active} active · ${_summary.currency}${_summary.monthly_total}/mo · ${_summary.currency}${_summary.yearly_total}/yr`
      : '';
  }
  const list = $('subs-list');
  if (!list) return;
  if (!_subs.length) {
    list.innerHTML = '<div style="padding:1rem 0;font-size:0.75rem;color:var(--faint)">nothing tracked yet — add your first subscription below</div>';
    return;
  }
  list.innerHTML = _subs.map(s => _editing === s.id ? _editRow(s) : _row(s)).join('');
  _wireRows(list);
}

function _row(s) {
  const soon = s.active && s.days_until <= 3;
  return `
    <div class="sub-item${s.active ? '' : ' paused'}" data-id="${s.id}">
      <div class="sub-main">
        <span class="sub-name">${esc(s.name)}</span>
        ${s.category ? `<span class="sub-cat">${esc(s.category)}</span>` : ''}
        ${s.notes ? `<span class="sub-notes" title="${esc(s.notes)}">…</span>` : ''}
      </div>
      <span class="sub-price">${esc(s.currency)}${s.price ? s.price.toFixed(2) : '—'}<span class="sub-cycle">${_cycleLabel(s)}</span></span>
      <span class="sub-due${soon ? ' soon' : ''}" title="${esc(s.next_due)}">${s.active ? esc(s.next_due.slice(5)) + ' · ' : ''}${_dueLabel(s)}</span>
      <span class="sub-actions">
        ${s.active ? `<button class="btn" data-act="paid" title="paid — advance one cycle">paid</button>` : ''}
        <button class="btn" data-act="toggle">${s.active ? 'pause' : 'resume'}</button>
        <button class="btn" data-act="edit">edit</button>
        <button class="btn danger" data-act="del">×</button>
      </span>
    </div>`;
}

function _editRow(s) {
  return `
    <div class="sub-item editing" data-id="${s.id}">
      <input type="text" class="settings-input" data-f="name" value="${esc(s.name)}" placeholder="name" style="flex:2;min-width:110px">
      <input type="text" class="settings-input" data-f="currency" value="${esc(s.currency)}" style="width:40px" title="currency symbol">
      <input type="text" class="settings-input" data-f="price" value="${s.price || ''}" placeholder="price" style="width:70px" inputmode="decimal">
      <div class="settings-input custom-select" data-f="cycle" data-value="${esc(s.cycle || 'monthly')}" data-options="weekly|weekly;monthly|monthly;quarterly|quarterly;yearly|yearly;custom|custom" style="width:auto;min-width:96px"></div>
      <input type="text" class="settings-input" data-f="cycle_days" value="${s.cycle_days}" style="width:55px;${s.cycle === 'custom' ? '' : 'display:none'}" title="cycle length in days" inputmode="numeric">
      <div class="date-input" data-f="next_due" data-type="date" data-value="${esc(s.next_due)}" data-ph="due" style="width:135px"></div>
      <input type="text" class="settings-input" data-f="category" value="${esc(s.category)}" placeholder="category" style="width:95px">
      <input type="text" class="settings-input" data-f="remind_days" value="${s.remind_days}" style="width:45px" title="push reminder N days before (0 = off)" inputmode="numeric">
      <input type="text" class="settings-input" data-f="notes" value="${esc(s.notes)}" placeholder="notes" style="flex:1;min-width:80px">
      <span class="sub-actions">
        <button class="btn primary" data-act="save">save</button>
        <button class="btn" data-act="cancel">cancel</button>
      </span>
    </div>`;
}

function _wireRows(list) {
  list.querySelectorAll('.sub-item.editing .custom-select').forEach(initCustomDropdown);
  list.querySelectorAll('.sub-item.editing .date-input').forEach(initDatePicker);
  list.querySelectorAll('.sub-item').forEach(row => {
    const id = row.dataset.id;
    const cycleSel = row.querySelector('[data-f="cycle"]');
    cycleSel?.addEventListener('change', () => {
      row.querySelector('[data-f="cycle_days"]').style.display = cycleSel.value === 'custom' ? '' : 'none';
    });
    row.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', async () => {
      const act = btn.dataset.act;
      if (act === 'edit') { _editing = id; _render(); return; }
      if (act === 'cancel') { _editing = null; _render(); return; }
      if (act === 'del') {
        const s = _subs.find(x => x.id === id);
        if (!await dlgConfirm(`stop tracking ${s?.name || 'this subscription'}?`)) return;
        await fetch(`/api/subscriptions/${id}`, { method: 'DELETE' });
        loadSubs(); return;
      }
      if (act === 'paid') {
        const r = await fetch(`/api/subscriptions/${id}/paid`, { method: 'POST' });
        if (r.ok) toast(`next due ${(await r.json()).next_due}`, 'success');
        loadSubs(); return;
      }
      if (act === 'toggle') {
        const s = _subs.find(x => x.id === id);
        await fetch(`/api/subscriptions/${id}`, {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ active: !s.active }),
        });
        loadSubs(); return;
      }
      if (act === 'save') {
        const v = f => row.querySelector(`[data-f="${f}"]`)?.value;
        const body = {
          name: v('name')?.trim(), currency: v('currency') || '$',
          price: parseFloat(v('price')) || 0,
          cycle: v('cycle'), cycle_days: parseInt(v('cycle_days')) || 30,
          next_due: v('next_due'), category: v('category')?.trim() || '',
          remind_days: parseInt(v('remind_days')) || 0,
          notes: v('notes') || '',
        };
        const r = await fetch(`/api/subscriptions/${id}`, {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!r.ok) { toast((await r.json()).detail || 'save failed', 'error'); return; }
        _editing = null;
        toast('saved', 'success');
        loadSubs(); return;
      }
    }));
  });
}

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

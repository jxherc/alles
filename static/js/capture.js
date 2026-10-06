import { confirm as confirmDialog } from './dialog.js';
import { createFocusBoundary } from './kokuen.js?v=1';
import { initDatePickers } from './datepick.js';
import { populateDropdown, getDropdownValue } from './dropdown.js?v=212';
import { resolvedTimeZone } from './i18n.js';
import { toast } from './util.js';
import { recordTarget } from './recordlinks.js';
import { editorDates, eventTimeValues } from './calendar.js';

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const PREFIX = 'alles.capture.pending.v1:';
let active = false;
const eventInstant = value => Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : value + 'Z');

async function pendingStore() {
  const response = await fetch('/api/tasks/draft-scope', { cache: 'no-store' });
  if (!response.ok) throw new Error('could not prepare recovery; try again');
  const { scopes } = await response.json();
  if (!Array.isArray(scopes) || !scopes.length || scopes.some(scope => !/^[a-f0-9]{64}$/.test(scope))) throw new Error('could not prepare recovery; try again');
  const keys = scopes.map(scope => PREFIX + scope);
  let pending = null;
  for (const key of keys) {
    const raw = sessionStorage.getItem(key);
    if (!raw) continue;
    const value = JSON.parse(raw);
    if (!['task', 'event'].includes(value?.kind) || typeof value.body?.request_id !== 'string') throw new Error('could not read the pending capture');
    pending ||= value;
  }
  return {
    pending,
    put(value) {
      const raw = JSON.stringify(value);
      sessionStorage.setItem(keys[0], raw);
      if (sessionStorage.getItem(keys[0]) !== raw) throw new Error('could not keep this acceptance for retry');
    },
    clear() { for (const key of keys) sessionStorage.removeItem(key); },
  };
}

function requestId() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export async function showPendingCapture(host, onSaved = null) {
  try {
    const store = await pendingStore();
    host.querySelector('.capture-resume[data-capture-recovery]')?.remove();
    if (!store.pending || !host.isConnected) return;
    const notice = document.createElement('div');
    notice.className = 'capture-resume';
    notice.dataset.captureRecovery = '';
    notice.innerHTML = '<span>a capture still needs confirmation</span><button class="btn" type="button">review pending capture</button>';
    notice.querySelector('button').onclick = event => openCaptureReview(null, event.currentTarget, onSaved).catch(error => toast(error.message, 'error'));
    host.prepend(notice);
  } catch { /* Acceptance reports a recovery error before sending any write. */ }
}

export async function openCaptureReview(proposal, trigger, onSaved = null) {
  if (active) return false;
  active = true;
  let store;
  try { store = await pendingStore(); }
  catch (error) { active = false; throw error; }
  if (trigger && (!trigger.isConnected || !trigger.getClientRects().length)) { active = false; return false; }
  const recovered = store.pending;
  if (!recovered && !proposal) { active = false; return false; }
  const kind = recovered?.kind || proposal.kind;
  const candidate = recovered?.body || proposal.candidate;
  const source = recovered?.body.source || proposal.source;
  const dates = kind === 'event' ? editorDates(candidate) : null;
  const initialTimes = dates && { start: candidate.all_day ? '09:00' : dates.start.slice(11) || '09:00', end: candidate.all_day ? '10:00' : dates.end.slice(11) || '10:00' };
  let frozen = recovered?.body || null;
  let busy = false, saved = null, confirming = false;
  const ov = document.createElement('div');
  ov.className = 'capture-overlay';
  ov.innerHTML = `<section class="capture-review" role="dialog" aria-modal="true" aria-labelledby="capture-heading">
    <h2 id="capture-heading">review ${kind === 'task' ? 'task' : 'event'} for plan</h2>
    <p>edit the details, then add it to plan.</p>
    ${source?.kind === 'aide' && source.private ? '<p>adding this task saves a copy of the reply in plan, outside this private conversation.</p>' : ''}
    ${source ? `<details class="capture-source"><summary>${esc(source.label || 'original message')}</summary><pre>${esc(source.excerpt)}</pre></details>` : ''}
    <div class="capture-fields">
      <label for="capture-title">title</label><input class="settings-input" id="capture-title" value="${esc(candidate.title)}">
      ${kind === 'task' ? `
        <label for="capture-due">due date</label><div id="capture-due" class="date-input" data-type="date" data-value="${esc(candidate.due_date || '')}" aria-label="due date"></div>
        <label id="capture-priority-label">priority</label><div class="settings-input custom-select" id="capture-priority" aria-labelledby="capture-priority-label"></div>
        <label id="capture-repeat-label">repeat</label><div class="settings-input custom-select" id="capture-repeat" aria-labelledby="capture-repeat-label"></div>
        <label for="capture-tags">tags</label><input class="settings-input" id="capture-tags" value="${esc(candidate.tags || '')}">
        <label for="capture-project">project</label><input class="settings-input" id="capture-project" value="${esc(candidate.project || '')}">
        <label for="capture-notes">notes</label><textarea class="settings-input" id="capture-notes">${esc(candidate.notes || '')}</textarea>
      ` : `
        <button class="btn" id="capture-all-day" type="button" role="switch" aria-checked="${Boolean(candidate.all_day)}">all day</button>
        <label for="capture-start">starts</label><div class="date-input" id="capture-start" data-type="${candidate.all_day ? 'date' : 'datetime'}" data-value="${esc(candidate.all_day ? dates.start.slice(0, 10) : dates.start)}" aria-label="starts"></div>
        <label for="capture-end">ends</label><div class="date-input" id="capture-end" data-type="${candidate.all_day ? 'date' : 'datetime'}" data-value="${esc(candidate.all_day ? dates.end.slice(0, 10) : dates.end)}" aria-label="ends"></div>
        <p>time zone: ${esc(resolvedTimeZone())}</p>
        <label for="capture-location">location</label><input class="settings-input" id="capture-location" value="${esc(candidate.location || '')}">
        <label for="capture-notes">description</label><textarea class="settings-input" id="capture-notes">${esc(candidate.description || '')}</textarea>
      `}
    </div>
    <p class="capture-status" role="status" tabindex="-1"></p>
    <div class="capture-actions"><button class="btn" id="capture-cancel" type="button">cancel</button><button class="btn primary" id="capture-accept" type="button">add to plan</button><button class="btn primary" id="capture-open" type="button" hidden>open in plan</button></div>
  </section>`;
  document.body.appendChild(ov);
  const dialog = ov.querySelector('.capture-review'), fields = ov.querySelector('.capture-fields');
  const status = ov.querySelector('.capture-status'), accept = ov.querySelector('#capture-accept');
  const cancel = ov.querySelector('#capture-cancel'), open = ov.querySelector('#capture-open');
  const el = name => ov.querySelector('#capture-' + name);
  initDatePickers(ov);
  if (kind === 'task') {
    populateDropdown(el('priority'), [0, 1, 2, 3].map((value, i) => ({ value, label: ['none', 'low', 'medium', 'high'][i] })), candidate.priority || 0);
    populateDropdown(el('repeat'), ['', 'daily', 'weekly', 'monthly', 'yearly'].map(value => ({ value, label: value || 'none' })), candidate.repeat || '');
  } else el('all-day').onclick = () => {
    const allDay = el('all-day').getAttribute('aria-checked') !== 'true';
    el('all-day').setAttribute('aria-checked', String(allDay));
    for (const name of ['start', 'end']) {
      const control = el(name);
      if (allDay && control.value.includes('T')) initialTimes[name] = control.value.slice(11);
      control.dataset.type = allDay ? 'date' : 'datetime';
      control.value = control.value ? (allDay ? control.value.slice(0, 10) : control.value.slice(0, 10) + 'T' + initialTimes[name]) : '';
    }
  };
  const focus = createFocusBoundary(dialog, { trigger, onEscape: () => close() });
  function lock() {
    fields.inert = Boolean(frozen || saved || busy);
    accept.disabled = busy;
    accept.hidden = Boolean(saved);
    accept.textContent = busy ? 'saving…' : frozen ? 'retry confirmation' : 'add to plan';
    cancel.disabled = busy;
    cancel.textContent = saved ? 'close' : frozen ? 'discard retry' : 'cancel';
    open.hidden = !saved;
    dialog.setAttribute('aria-busy', String(busy));
  }
  async function close({ restoreFocus = true } = {}) {
    if (busy || confirming) return false;
    if (frozen && !saved) {
      confirming = true; dialog.inert = true;
      let discard;
      try { discard = await confirmDialog('this item may already be in plan. discard the saved retry? check plan before adding it again.'); }
      finally { confirming = false; dialog.inert = false; }
      if (!discard) { cancel.focus(); return false; }
    }
    let cleared = false;
    try { store.clear(); cleared = true; }
    catch {
      if (!saved) { status.textContent = 'could not clear the saved retry; try closing again'; status.focus(); return false; }
    }
    focus.deactivate({ restoreFocus }); focus.destroy(); ov.remove(); active = false;
    if (cleared) document.querySelectorAll('.capture-resume[data-capture-recovery]').forEach(node => node.remove());
    return true;
  }
  cancel.onclick = () => close();
  ov.onclick = event => { if (event.target === ov) close(); };
  open.onclick = async () => {
    const target = recordTarget(kind === 'task' ? 'tasks' : 'calendar', saved.id);
    if (await close({ restoreFocus: false })) await window._openRecord?.(target.view, target.id);
  };
  accept.onclick = async () => {
    if (busy || saved) return;
    const retrying = Boolean(frozen);
    let attemptedSave = false;
    try {
      if (!frozen) {
        const title = el('title').value.trim();
        if (!title) { status.textContent = 'add a title'; el('title').focus(); return; }
        const body = { ...candidate, title, source, request_id: requestId() };
        if (kind === 'task') Object.assign(body, { due_date: el('due').value || null, priority: Number(getDropdownValue(el('priority'))), repeat: getDropdownValue(el('repeat')), tags: el('tags').value, project: el('project').value, notes: el('notes').value });
        else {
          const allDay = el('all-day').getAttribute('aria-checked') === 'true';
          const start = el('start').value, end = el('end').value;
          if (!start || (!allDay && !start.includes('T')) || (allDay && end && end < start)) { status.textContent = 'choose a valid start and an end after it'; el('start').focus(); return; }
          const times = allDay ? { start_dt: start, end_dt: end || null }
            : eventTimeValues(candidate.all_day ? null : candidate, dates, { start, end });
          // Repeated autumn clock times can be equal while their original instants differ.
          if (!allDay && (!Number.isFinite(eventInstant(times.start_dt)) || (times.end_dt && (!Number.isFinite(eventInstant(times.end_dt)) || eventInstant(times.end_dt) <= eventInstant(times.start_dt))))) {
            status.textContent = 'choose a valid start and an end after it'; el('start').focus(); return;
          }
          Object.assign(body, { all_day: allDay, ...times, location: el('location').value, description: el('notes').value });
        }
        store.put({ kind, body }); frozen = body;
      }
      attemptedSave = true; busy = true; lock(); status.textContent = 'confirming the saved item…'; status.focus();
      const response = await fetch(kind === 'task' ? '/api/tasks' : '/api/calendar', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(frozen) });
      const data = await response.json();
      if (!response.ok) {
        // A rejected retry says nothing about whether an earlier attempt committed.
        if (!retrying && [400, 401, 403, 422].includes(response.status)) { store.clear(); frozen = null; }
        throw new Error(typeof data.detail === 'string' ? data.detail : 'could not confirm this item; your details are still here');
      }
      if (!recordTarget(kind === 'task' ? 'tasks' : 'calendar', data?.id) || typeof data.title !== 'string' || (source && data.source?.fingerprint !== source.fingerprint)) throw new Error('plan did not confirm the item; retry confirmation');
      saved = data;
      status.textContent = `saved in plan: ${data.title}${data.done ? ' (completed)' : ''}`;
      try { store.clear(); }
      catch { status.textContent += '; its browser retry copy could not be cleared'; }
    } catch (error) { status.textContent = frozen ? `${error.message}. retry uses the same acceptance and cannot add a second item.` : error.message; }
    finally { busy = false; lock(); if (attemptedSave && dialog.contains(document.activeElement)) (saved ? open : accept).focus(); }
    if (saved) onSaved?.(saved, kind);
  };
  if (frozen) status.textContent = 'the previous acceptance was not confirmed. retry to check the same item.';
  lock(); focus.activate({ focus: frozen ? accept : el('title'), source: trigger });
  return true;
}

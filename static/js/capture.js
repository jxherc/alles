import { confirm as confirmDialog } from './dialog.js';
import { createFocusBoundary } from './kokuen.js?v=4';
import { initDatePickers } from './datepick.js';
import { populateDropdown, getDropdownValue } from './dropdown.js?v=215';
import { chosenTimeZone, resolvedTimeZone, t } from './i18n.js';
import { toast, plainError } from './util.js';
import { recordTarget } from './recordlinks.js';
import { editorDates, eventTimeValues, storedWallTime } from './calendar.js';

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const PREFIX = 'alles.capture.pending.v1:';
let active = false;
const wallInstant = value => Date.parse(String(value || '') + 'Z');

async function pendingStore() {
  const response = await fetch('/api/tasks/draft-scope', { cache: 'no-store' });
  if (!response.ok) throw new Error(t('home.capture_recovery_unprepared'));
  const { scopes } = await response.json();
  if (!Array.isArray(scopes) || !scopes.length || scopes.some(scope => !/^[a-f0-9]{64}$/.test(scope))) throw new Error(t('home.capture_recovery_unprepared'));
  const keys = scopes.map(scope => PREFIX + scope);
  let pending = null, pendingKey = null, pendingRaw = null;
  for (const key of keys) {
    const raw = sessionStorage.getItem(key);
    if (!raw) continue;
    const value = JSON.parse(raw);
    if (!['task', 'event'].includes(value?.kind) || typeof value.body?.request_id !== 'string') throw new Error(t('home.capture_pending_unreadable'));
    if (!pending) { pending = value; pendingKey = key; pendingRaw = raw; }
  }
  return {
    pending,
    put(value) {
      const raw = JSON.stringify(value);
      sessionStorage.setItem(keys[0], raw);
      if (sessionStorage.getItem(keys[0]) !== raw) throw new Error(t('home.capture_retry_unkept'));
      pendingKey = keys[0]; pendingRaw = raw;
    },
    clear() {
      if (pendingKey && sessionStorage.getItem(pendingKey) === pendingRaw) sessionStorage.removeItem(pendingKey);
    },
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
    notice.innerHTML = `<span>${esc(t('home.capture_needs_confirmation'))}</span><button class="btn" type="button">${esc(t('home.capture_review_pending'))}</button>`;
    notice.querySelector('button').onclick = event => openCaptureReview(null, event.currentTarget, onSaved).catch(error => toast(error.message, 'error'));
    host.prepend(notice);
  } catch { /* Acceptance reports a recovery error before sending any write. */ }
}

export async function openCaptureReview(proposal, trigger, onSaved = null, isCurrent = () => true) {
  if (active || !isCurrent()) return false;
  active = true;
  let store;
  try { store = await pendingStore(); }
  catch (error) { active = false; throw error; }
  if (!isCurrent() || (trigger && (!trigger.isConnected || !trigger.getClientRects().length))) { active = false; return false; }
  const recovered = store.pending;
  if (!recovered && !proposal) { active = false; return false; }
  const kind = recovered?.kind || proposal.kind;
  const candidate = recovered?.body || proposal.candidate;
  const source = recovered?.body.source || proposal.source;
  const dates = kind === 'event' ? editorDates(candidate) : null;
  const initialTimes = dates && { start: candidate.all_day ? '09:00' : dates.start.slice(11) || '09:00', end: candidate.all_day ? '10:00' : dates.end.slice(11) || '10:00' };
  let frozen = recovered?.body || null;
  let busy = false, saved = null, savedFocus = null, confirming = false;
  const ov = document.createElement('div');
  ov.className = 'capture-overlay';
  ov.innerHTML = `<section class="capture-review" role="dialog" aria-modal="true" aria-labelledby="capture-heading">
    <h2 id="capture-heading">${esc(kind === 'task' ? t('home.capture_review_task') : t('home.capture_review_event'))}</h2>
    <p>${esc(t('home.capture_edit_hint'))}</p>
    ${source?.kind === 'aide' && source.private ? `<p>${esc(t('home.capture_private_copy'))}</p>` : ''}
    ${source ? `<details class="capture-source"><summary>${esc(source.label || t('home.capture_original_message'))}</summary><pre>${esc(source.excerpt)}</pre></details>` : ''}
    <div class="capture-fields">
      <label for="capture-title">${esc(t('calendar.title_label'))}</label><input class="settings-input" id="capture-title" value="${esc(candidate.title)}">
      ${kind === 'task' ? `
        <label for="capture-due">${esc(t('home.capture_due_date'))}</label><div id="capture-due" class="date-input" data-type="date" data-value="${esc(candidate.due_date || '')}" aria-label="${esc(t('home.capture_due_date'))}"></div>
        <label id="capture-priority-label">${esc(t('home.capture_priority'))}</label><div class="settings-input custom-select" id="capture-priority" aria-labelledby="capture-priority-label"></div>
        <label id="capture-repeat-label">${esc(t('home.capture_repeat'))}</label><div class="settings-input custom-select" id="capture-repeat" aria-labelledby="capture-repeat-label"></div>
        <label for="capture-tags">${esc(t('home.capture_tags'))}</label><input class="settings-input" id="capture-tags" value="${esc(candidate.tags || '')}">
        <label for="capture-project">${esc(t('home.capture_project'))}</label><input class="settings-input" id="capture-project" value="${esc(candidate.project || '')}">
        <label for="capture-notes">${esc(t('home.capture_notes'))}</label><textarea class="settings-input" id="capture-notes">${esc(candidate.notes || '')}</textarea>
      ` : `
        <button class="btn" id="capture-all-day" type="button" role="switch" aria-checked="${Boolean(candidate.all_day)}">${esc(t('home.capture_all_day'))}</button>
        <label for="capture-start">${esc(t('home.capture_starts'))}</label><div class="date-input" id="capture-start" data-type="${candidate.all_day ? 'date' : 'datetime'}" data-value="${esc(candidate.all_day ? dates.start.slice(0, 10) : dates.start)}" aria-label="${esc(t('home.capture_starts'))}"></div>
        <label for="capture-end">${esc(t('home.capture_ends'))}</label><div class="date-input" id="capture-end" data-type="${candidate.all_day ? 'date' : 'datetime'}" data-value="${esc(candidate.all_day ? dates.end.slice(0, 10) : dates.end)}" aria-label="${esc(t('home.capture_ends'))}"></div>
        <p>${esc(t('home.capture_time_zone', { zone: resolvedTimeZone() }))}</p>
        <label for="capture-location">${esc(t('calendar.location'))}</label><input class="settings-input" id="capture-location" value="${esc(candidate.location || '')}">
        <label for="capture-notes">${esc(t('home.capture_description'))}</label><textarea class="settings-input" id="capture-notes">${esc(candidate.description || '')}</textarea>
      `}
    </div>
    <p class="capture-status" role="status" tabindex="-1"></p>
    <div class="capture-actions"><button class="btn" id="capture-cancel" type="button">${esc(t('common.cancel'))}</button><button class="btn primary" id="capture-accept" type="button">${esc(t('home.capture_add_to_plan'))}</button><button class="btn primary" id="capture-open" type="button" hidden>${esc(t('home.capture_open_in_plan'))}</button></div>
  </section>`;
  document.body.appendChild(ov);
  const dialog = ov.querySelector('.capture-review'), fields = ov.querySelector('.capture-fields');
  const status = ov.querySelector('.capture-status'), accept = ov.querySelector('#capture-accept');
  const cancel = ov.querySelector('#capture-cancel'), open = ov.querySelector('#capture-open');
  const el = name => ov.querySelector('#capture-' + name);
  initDatePickers(ov);
  if (kind === 'task') {
    populateDropdown(el('priority'), [0, 1, 2, 3].map((value, i) => ({ value, label: [t('home.capture_none'), t('home.capture_low'), t('home.capture_medium'), t('home.capture_high')][i] })), candidate.priority || 0);
    populateDropdown(el('repeat'), ['', 'daily', 'weekly', 'monthly', 'yearly'].map(value => ({ value, label: value ? t(`home.capture_${value}`) : t('home.capture_none') })), candidate.repeat || '');
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
  const focusLost = () => !document.activeElement || document.activeElement === document.body;
  // a click on the disabled button drops focus to body, where the boundary can't hear escape
  const onLostEscape = event => {
    if (event.key !== 'Escape' || event.defaultPrevented || !focusLost()) return;
    event.preventDefault();
    close();
  };
  document.addEventListener('keydown', onLostEscape);
  function lock() {
    fields.inert = Boolean(frozen || saved || busy);
    accept.disabled = busy;
    accept.hidden = Boolean(saved);
    accept.textContent = busy ? t('common.saving') : frozen ? t('home.capture_retry_confirmation') : t('home.capture_add_to_plan');
    cancel.disabled = busy;
    cancel.textContent = saved ? t('home.capture_close') : frozen ? t('home.capture_discard_retry') : t('common.cancel');
    open.hidden = !saved;
    dialog.setAttribute('aria-busy', String(busy));
  }
  async function close({ restoreFocus = true } = {}) {
    if (busy || confirming) return false;
    if (frozen && !saved) {
      confirming = true; dialog.inert = true;
      let discard;
      try { discard = await confirmDialog(t('home.capture_discard_confirm')); }
      finally { confirming = false; dialog.inert = false; }
      if (!discard) { cancel.focus(); return false; }
    }
    let cleared = false;
    try { store.clear(); cleared = true; }
    catch {
      if (!saved) { status.textContent = t('home.capture_clear_failed'); status.focus(); return false; }
    }
    focus.deactivate({ restoreFocus }); focus.destroy(); ov.remove(); active = false;
    document.removeEventListener('keydown', onLostEscape);
    if (cleared) document.querySelectorAll('.capture-resume[data-capture-recovery]').forEach(node => node.remove());
    if (restoreFocus && !trigger?.isConnected && savedFocus?.isConnected && savedFocus.getClientRects().length) savedFocus.focus();
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
        if (!title) { status.textContent = t('home.capture_add_title'); el('title').focus(); return; }
        const body = { ...candidate, title, source, request_id: requestId() };
        if (kind === 'task') Object.assign(body, { due_date: el('due').value || null, priority: Number(getDropdownValue(el('priority'))), repeat: getDropdownValue(el('repeat')), tags: el('tags').value, project: el('project').value, notes: el('notes').value });
        else {
          const allDay = el('all-day').getAttribute('aria-checked') === 'true';
          const start = el('start').value, end = el('end').value;
          if (!start || (!allDay && !start.includes('T')) || (allDay && end && end < start)) { status.textContent = t('home.capture_invalid_range'); el('start').focus(); return; }
          const times = allDay ? { start_dt: start, end_dt: end || null }
            : eventTimeValues(candidate.all_day ? null : candidate, dates, { start, end });
          // plan keeps wall time, so a zoned proposal is saved as the time shown here
          if (!allDay) for (const key of ['start_dt', 'end_dt']) times[key] = storedWallTime(times[key]);
          if (!allDay && (!Number.isFinite(wallInstant(times.start_dt)) || (times.end_dt && (!Number.isFinite(wallInstant(times.end_dt)) || wallInstant(times.end_dt) <= wallInstant(times.start_dt))))) {
            status.textContent = t('home.capture_invalid_range'); el('start').focus(); return;
          }
          Object.assign(body, { all_day: allDay, ...times, location: el('location').value, description: el('notes').value });
        }
        store.put({ kind, body }); frozen = body;
      }
      attemptedSave = true; busy = true; lock(); status.textContent = t('home.capture_confirming'); status.focus();
      const zone = kind === 'event' && chosenTimeZone() ? { 'x-alles-time-zone': chosenTimeZone() } : {};
      const response = await fetch(kind === 'task' ? '/api/tasks' : '/api/calendar', { method: 'POST', headers: { 'content-type': 'application/json', ...zone }, body: JSON.stringify(frozen) });
      const data = await response.json();
      if (!response.ok) {
        // A rejected retry says nothing about whether an earlier attempt committed.
        if (!retrying && [400, 401, 403, 422].includes(response.status)) { store.clear(); frozen = null; }
        const error = new Error(typeof data.detail === 'string' ? data.detail : t('home.capture_item_unconfirmed'));
        error.status = response.status;
        throw error;
      }
      if (!recordTarget(kind === 'task' ? 'tasks' : 'calendar', data?.id) || typeof data.title !== 'string' || (source && data.source?.fingerprint !== source.fingerprint)) throw new Error(t('home.capture_plan_unconfirmed'));
      saved = data;
      status.textContent = t(data.done ? 'home.capture_saved_completed' : 'home.capture_saved_in_plan', { title: data.title });
      try { store.clear(); }
      catch { status.textContent += t('home.capture_copy_not_cleared'); }
    } catch (error) { status.textContent = frozen && error.status !== 410 ? t(`home.capture_save_unconfirmed_${kind}`) : plainError(error.message); }
    finally { busy = false; lock(); if (attemptedSave && (focusLost() || dialog.contains(document.activeElement))) (saved ? open : accept).focus(); }
    if (saved) savedFocus = onSaved?.(saved, kind);
  };
  if (frozen) status.textContent = t(`home.capture_frozen_${kind}`);
  lock(); focus.activate({ focus: frozen ? accept : el('title'), source: trigger });
  if (frozen) dialog.scrollTop = dialog.scrollHeight;
  return true;
}

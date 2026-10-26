// per-app settings — a gear in an app's header opens a small popover of just that
// app's options, saved to settings.json. custom controls only (no native selects).
import { t } from './i18n.js';

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const appSpecs = () => ({
  notes: { title: t('settings.app_notes_docs'), apply: () => window._reloadNotes?.(), fields: [
    { k: 'vault_dir', type: 'text', label: t('settings.app_vault_folder'), ph: 'data/vault' },
    { type: 'note', text: t('settings.app_notes_location_note') },
    { type: 'action', label: t('settings.app_open_in_obsidian'), act: '_openInObsidian' },
    { type: 'action', label: t('settings.app_copy_vault_path'), act: '_copyVaultPath' },
    { type: 'note', text: t('settings.app_notes_sync_note') },
    { type: 'action', label: t('settings.app_download_obsidian_plugin'), act: '_downloadPlugin' },
  ] },
  files: { title: t('settings.app_files'), apply: () => window._reloadFiles?.(), fields: [
    { k: 'files_dir', type: 'text', label: t('settings.app_root_directory'), ph: 'data/files' },
  ] },
  photos: { title: t('settings.app_gallery'), apply: () => window._reloadPhotos?.(), fields: [
    { k: 'photos_dir', type: 'text', label: t('settings.app_library_folder'), ph: 'data/photos' },
    { k: 'photos_watch_folder', type: 'text', label: t('settings.app_phone_backup_watch_folder'), ph: t('settings.app_watch_folder_example') },
  ] },
  calendar: { title: t('settings.app_calendar'), apply: () => window._reloadCalendar?.(), fields: [
    { k: 'cal_default_view', type: 'choice', label: t('settings.app_default_view'), opts: [['month', t('settings.app_opt_month')], ['week', t('settings.app_opt_week')]] },
    { k: 'cal_default_duration_min', type: 'choice', num: true, label: t('settings.app_default_duration'), opts: [['30', t('settings.app_opt_30_min')], ['60', t('settings.app_opt_1_hour')], ['90', t('settings.app_opt_90_min')], ['120', t('settings.app_opt_2_hours')]] },
    { k: 'cal_work_start', type: 'text', num: true, label: t('settings.app_work_start'), ph: '9' },
    { k: 'cal_work_end', type: 'text', num: true, label: t('settings.app_work_end'), ph: '18' },
    { k: 'cal_secondary_tz', type: 'text', label: t('settings.app_second_time_zone'), ph: t('settings.app_time_zone_example') },
  ] },
  system: { title: t('settings.app_system_monitor'), apply: () => window._reloadSystem?.(), fields: [
    { k: 'system_refresh', type: 'choice', num: true, label: t('settings.app_refresh_rate'), opts: [['1000', t('settings.app_opt_1s')], ['1500', t('settings.app_opt_1_5s')], ['3000', t('settings.app_opt_3s')], ['5000', t('settings.app_opt_5s')]] },
  ] },
  mail: { title: t('settings.app_mail'), apply: () => window._reloadMail?.(), fields: [
    { k: 'mail_poll_seconds', type: 'choice', num: true, label: t('settings.app_check_every'), opts: [['30', t('settings.app_opt_30s')], ['60', t('settings.app_opt_1m')], ['300', t('settings.app_opt_5m')]] },
    { k: 'mail_threads', type: 'choice', label: t('settings.app_message_grouping'), opts: [['flat', t('settings.app_opt_flat')], ['group', t('settings.app_opt_grouped')]] },
    { k: 'mail_signature', type: 'textarea', label: t('settings.app_signature'), ph: '-- sent from alles' },
    { type: 'action', label: t('settings.app_accounts'), act: '_mailAccounts' },
    { type: 'action', label: t('settings.app_mail_rules'), act: '_mailRules' },
  ] },
  contacts: { title: t('settings.app_contacts'), fields: [
    { type: 'action', label: t('settings.app_carddav_sync'), act: '_contactsCardDav' },
  ] },
  journal: { title: t('settings.app_journal'), apply: () => window._reloadJournal?.(), fields: [
    { k: 'journal_mirror_vault', type: 'toggle', label: t('settings.app_journal_mirror') },
    { type: 'note', text: t('settings.app_journal_mirror_note') },
  ] },
});

let _open = null;

export function appSettingValue(el) {
  const v = (el.value || '').trim();
  if (el.dataset.num !== '1') return v;
  if (v === '') return '';
  const n = Number(v);
  return Number.isFinite(n) ? n : v;
}

export function renderAppSettingField(f, val) {
  if (f.type === 'choice') {
    return `<div class="aps-field"><label>${f.label}</label><div class="seg" data-k="${f.k}"${f.num ? ' data-num="1"' : ''} role="group" aria-label="${esc(f.label)}">` +
      f.opts.map(([v, l]) => `<button type="button" class="seg-opt${String(val) === String(v) ? ' active' : ''}" data-val="${v}" aria-pressed="${String(val) === String(v)}">${l}</button>`).join('') + `</div></div>`;
  }
  if (f.type === 'toggle') {
    return `<div class="aps-field aps-toggle" style="display:flex;align-items:center;justify-content:space-between;gap:10px"><label style="margin:0">${f.label}</label><div class="s-switch${val ? ' on' : ''}" data-tk="${f.k}" role="switch" tabindex="0" aria-checked="${Boolean(val)}" aria-label="${esc(f.label)}"></div></div>`;
  }
  if (f.type === 'note') return `<div class="aps-note" style="font-size:0.8125rem;opacity:0.7;line-height:1.45;margin:2px 0 6px">${esc(f.text)}</div>`;
  if (f.type === 'action') return `<button type="button" class="aps-action" data-act="${esc(f.act)}">${esc(f.label)}</button>`;
  if (f.type === 'textarea') return `<div class="aps-field"><label>${f.label}</label><textarea class="settings-textarea" data-k="${f.k}" rows="2" placeholder="${esc(f.ph || '')}">${esc(val || '')}</textarea></div>`;
  const num = f.num ? ' data-num="1" inputmode="numeric"' : '';
  return `<div class="aps-field"><label>${f.label}</label><input class="settings-input" data-k="${f.k}"${num} placeholder="${esc(f.ph || '')}" value="${esc(val ?? '')}"></div>`;
}

function _patch(spec, k, v) {
  fetch('/api/settings', { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ [k]: v }) })
    .then(() => spec.apply?.()).catch(() => {});
}

// built-in actions (the "connect to Obsidian" buttons), resolved before any window.* hook
async function _vaultLoc() {
  return fetch('/api/vault-location').then(r => r.json()).catch(() => null);
}
async function _openInObsidian() {
  const loc = await _vaultLoc();
  if (loc?.obsidian) location.href = loc.obsidian;  // best-effort; needs the folder added as a vault
}
async function _copyVaultPath() {
  const loc = await _vaultLoc();
  if (!loc?.path) return;
  try { await navigator.clipboard.writeText(loc.path); } catch {}
  import('./util.js').then(m => m.toast?.(t('settings.app_vault_path_copied'), 'success')).catch(() => {});
}
function _downloadPlugin() { location.href = '/api/download/obsidian-plugin'; }
const ACTIONS = { _openInObsidian, _copyVaultPath, _downloadPlugin };

// focus goes back to the button that opened it, unless the person already moved somewhere else
export function closeAppSettings({ restoreFocus = true } = {}) {
  if (!_open) return;
  const { pop, anchor, place } = _open;
  const held = !document.activeElement || document.activeElement === document.body || pop.contains(document.activeElement);
  pop.remove(); document.removeEventListener('click', _outside); _open = null;
  window.removeEventListener('resize', place);
  window.visualViewport?.removeEventListener('resize', place);
  if (restoreFocus && held && anchor?.isConnected) anchor.focus();
}
function _outside(e) {
  if (_open && !_open.pop.contains(e.target) && !e.target.closest('.app-cog')) closeAppSettings();
}

export async function openAppSettings(app, anchor) {
  if (_open?.app === app) { closeAppSettings(); return; }
  closeAppSettings();
  const spec = appSpecs()[app];
  if (!spec) return;
  const s = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
  if (_open) return;   // a second open raced this one's settings read
  const pop = document.createElement('div');
  pop.className = 'app-settings-pop';
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', t('settings.app_title_settings', { title: spec.title }));
  pop.tabIndex = -1;   // a tap on its text keeps focus in here, so escape still closes it
  pop.innerHTML = `<div class="app-settings-title">${esc(t('settings.app_title_settings', { title: spec.title }))}</div>` + spec.fields.map(f => renderAppSettingField(f, s[f.k])).join('');
  document.body.appendChild(pop);
  // a phone can be shorter than the popover: it never grows past the screen and scrolls inside,
  // opens below the button, above it when it only fits there, else pinned inside the screen
  pop.style.overflowY = 'auto';
  pop.style.overscrollBehavior = 'contain';
  const place = () => {
    if (!anchor.isConnected) return;
    const r = anchor.getBoundingClientRect();
    const vh = window.visualViewport?.height || window.innerHeight;
    pop.style.maxHeight = `${Math.max(120, vh - 16)}px`;
    const h = pop.offsetHeight;
    const top = r.bottom + 6 + h <= vh - 8 ? r.bottom + 6
      : r.top - 6 - h >= 8 ? r.top - 6 - h
      : Math.max(8, vh - 8 - h);
    pop.style.top = top + 'px';
    pop.style.left = Math.max(8, Math.min(r.right - pop.offsetWidth, window.innerWidth - pop.offsetWidth - 8)) + 'px';
  };
  place();
  window.addEventListener('resize', place);
  window.visualViewport?.addEventListener('resize', place);
  _open = { pop, app, anchor, place };
  const controls = () => [...pop.querySelectorAll('button, input, textarea, [role="switch"]')]
    .filter(node => !node.disabled && node.getClientRects().length);
  pop.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      e.preventDefault(); e.stopPropagation();
      closeAppSettings();
      return;
    }
    // tab is walked here, not left to the browser: safari's tab skips buttons, so its first stop
    // isn't ours. past either end it closes and hands focus back to the button that opened it,
    // since the popover lives at the end of the page, far from that button
    if (e.key !== 'Tab') return;
    const items = controls();
    if (!items.length) return;
    e.preventDefault();
    const at = items.indexOf(document.activeElement);
    const next = at < 0 ? (e.shiftKey ? items.length - 1 : 0) : at + (e.shiftKey ? -1 : 1);
    if (next < 0 || next >= items.length) closeAppSettings();
    else items[next].focus();
  });
  // focus leaving for somewhere else closes it, like clicking outside does. with no next target
  // (it went to the page) only a tap inside the popover itself keeps it open
  let pressedInside = false;
  pop.addEventListener('pointerdown', () => { pressedInside = true; setTimeout(() => { pressedInside = false; }, 0); });
  pop.addEventListener('focusout', e => {
    if (_open?.pop !== pop) return;
    if (e.relatedTarget) {
      if (!pop.contains(e.relatedTarget)) closeAppSettings({ restoreFocus: false });
      return;
    }
    const tappedInside = pressedInside;
    requestAnimationFrame(() => {
      if (_open?.pop === pop && !tappedInside && !pop.contains(document.activeElement)
          && (!document.activeElement || document.activeElement === document.body)) closeAppSettings();
    });
  });

  // choices (segmented)
  pop.querySelectorAll('.seg[data-k]').forEach(seg => {
    const num = seg.dataset.num === '1';
    seg.querySelectorAll('.seg-opt').forEach(opt => opt.addEventListener('click', () => {
      seg.querySelectorAll('.seg-opt').forEach(o => { o.classList.toggle('active', o === opt); o.setAttribute('aria-pressed', String(o === opt)); });
      _patch(spec, seg.dataset.k, num ? Number(opt.dataset.val) : opt.dataset.val);
    }));
  });
  // toggles
  pop.querySelectorAll('.s-switch[data-tk]').forEach(sw => sw.addEventListener('click', () => {
    const on = !sw.classList.contains('on');
    sw.classList.toggle('on', on);
    sw.setAttribute('aria-checked', String(on));
    _patch(spec, sw.dataset.tk, on);
  }));
  // text / textarea (debounced)
  pop.querySelectorAll('input[data-k], textarea[data-k]').forEach(el => {
    let t; el.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => _patch(spec, el.dataset.k, appSettingValue(el)), 500); });
  });
  // action buttons (e.g. mail's accounts / rules panels) → close the popover, run the hook
  pop.querySelectorAll('.aps-action').forEach(btn => btn.addEventListener('click', () => {
    closeAppSettings({ restoreFocus: false });
    (ACTIONS[btn.dataset.act] || window[btn.dataset.act])?.();
  }));
  setTimeout(() => document.addEventListener('click', _outside), 0);
  // keyboard and screen readers start inside: the chosen option of a choice, else the first control
  const first = pop.querySelector('button, input, textarea, [role="switch"]');
  (first?.closest('.seg')?.querySelector('.seg-opt.active') || first)?.focus();
}

let _cogsBound = false;
// wire any `.app-cog` button (data-app) found in the DOM
export function initAppCogs() {
  if (_cogsBound) return;
  _cogsBound = true;
  document.addEventListener('click', e => {
    const btn = e.target.closest('.app-cog');
    if (btn) { e.stopPropagation(); openAppSettings(btn.dataset.app, btn); }
  });
}

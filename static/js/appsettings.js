// per-app settings — a gear in an app's header opens a small popover of just that
// app's options, saved to settings.json. custom controls only (no native selects).
import { toast } from './util.js';

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const SPECS = {
  files: { title: 'files', apply: () => window._reloadFiles?.(), fields: [
    { k: 'files_dir', type: 'text', label: 'root directory', ph: 'data/files' },
  ] },
  photos: { title: 'gallery', apply: () => window._reloadPhotos?.(), fields: [
    { k: 'photos_dir', type: 'text', label: 'library folder', ph: 'data/photos' },
  ] },
  calendar: { title: 'calendar', apply: () => window._reloadCalendar?.(), fields: [
    { k: 'cal_default_view', type: 'choice', label: 'default view', opts: [['month', 'month'], ['week', 'week']] },
    { k: 'cal_week_start', type: 'choice', label: 'week starts on', opts: [['sun', 'sunday'], ['mon', 'monday']] },
  ] },
  system: { title: 'system monitor', apply: () => window._reloadSystem?.(), fields: [
    { k: 'system_refresh', type: 'choice', num: true, label: 'refresh rate', opts: [['1000', '1s'], ['1500', '1.5s'], ['3000', '3s'], ['5000', '5s']] },
  ] },
  mail: { title: 'mail', apply: () => window._reloadMail?.(), fields: [
    { k: 'mail_poll_seconds', type: 'choice', num: true, label: 'check every', opts: [['30', '30s'], ['60', '1m'], ['300', '5m']] },
    { k: 'mail_signature', type: 'textarea', label: 'signature', ph: '— sent from alles' },
  ] },
};

let _open = null;

function _field(f, val) {
  if (f.type === 'choice') {
    return `<div class="aps-field"><label>${f.label}</label><div class="seg" data-k="${f.k}"${f.num ? ' data-num="1"' : ''}>` +
      f.opts.map(([v, l]) => `<button type="button" class="seg-opt${String(val) === String(v) ? ' active' : ''}" data-val="${v}">${l}</button>`).join('') + `</div></div>`;
  }
  if (f.type === 'textarea') return `<div class="aps-field"><label>${f.label}</label><textarea class="settings-textarea" data-k="${f.k}" rows="2" placeholder="${esc(f.ph || '')}">${esc(val || '')}</textarea></div>`;
  return `<div class="aps-field"><label>${f.label}</label><input class="settings-input" data-k="${f.k}" placeholder="${esc(f.ph || '')}" value="${esc(val || '')}" style="width:100%"></div>`;
}

function _patch(spec, k, v) {
  fetch('/api/settings', { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ [k]: v }) })
    .then(() => spec.apply?.()).catch(() => {});
}

export function closeAppSettings() {
  if (_open) { _open.pop.remove(); document.removeEventListener('click', _outside); _open = null; }
}
function _outside(e) {
  if (_open && !_open.pop.contains(e.target) && !e.target.closest('.app-cog')) closeAppSettings();
}

export async function openAppSettings(app, anchor) {
  if (_open?.app === app) { closeAppSettings(); return; }
  closeAppSettings();
  const spec = SPECS[app];
  if (!spec) return;
  const s = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
  const pop = document.createElement('div');
  pop.className = 'app-settings-pop';
  pop.innerHTML = `<div class="app-settings-title">${spec.title} settings</div>` + spec.fields.map(f => _field(f, s[f.k])).join('');
  document.body.appendChild(pop);
  const r = anchor.getBoundingClientRect();
  pop.style.top = (r.bottom + 6) + 'px';
  pop.style.left = Math.max(8, Math.min(r.right - pop.offsetWidth, window.innerWidth - pop.offsetWidth - 8)) + 'px';
  _open = { pop, app };

  // choices (segmented)
  pop.querySelectorAll('.seg[data-k]').forEach(seg => {
    const num = seg.dataset.num === '1';
    seg.querySelectorAll('.seg-opt').forEach(opt => opt.addEventListener('click', () => {
      seg.querySelectorAll('.seg-opt').forEach(o => o.classList.toggle('active', o === opt));
      _patch(spec, seg.dataset.k, num ? Number(opt.dataset.val) : opt.dataset.val);
    }));
  });
  // text / textarea (debounced)
  pop.querySelectorAll('input[data-k], textarea[data-k]').forEach(el => {
    let t; el.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => _patch(spec, el.dataset.k, el.value.trim()), 500); });
  });
  setTimeout(() => document.addEventListener('click', _outside), 0);
}

// wire any `.app-cog` button (data-app) found in the DOM
export function initAppCogs() {
  document.querySelectorAll('.app-cog').forEach(btn => {
    if (btn.dataset.cogBound) return;
    btn.dataset.cogBound = '1';
    btn.addEventListener('click', e => { e.stopPropagation(); openAppSettings(btn.dataset.app, btn); });
  });
}

import { toast } from './util.js';
import { confirm as _dlgConfirm, prompt as _dlgPrompt, fields as _dlgFields } from './dialog.js';
import { initCustomDropdown, getDropdownValue, populateDropdown } from './dropdown.js?v=215';
import { formatDate, formatTime, t, tp } from './i18n.js';
import { pushRouteUrl, routeHistoryPosition } from './route_history.js';

// 4a - typed relationship kinds (mirrors services/contacts_graph _INVERSE)
const REL_KINDS = ['friend', 'colleague', 'spouse', 'partner', 'sibling', 'parent', 'child', 'manager', 'report', 'mentor', 'mentee'];
const _relLabel = kind => REL_KINDS.includes(kind) ? t('contacts.rel_' + kind) : kind;

let _favOnly = false;
let _wired = false;
let _creatingContact = false;
let _contactsLoad = 0;
// an open contact has its own history entry, so Back returns to the list; focus lands on its row
let _contactEntry = null, _returnTo = null;
const _si = n => (window.icon ? window.icon(n) : '');   // central icon set, load-order safe

function _wire() {
  if (_wired) return; _wired = true;
  const btn = document.getElementById('contacts-fav-filter');
  btn?.addEventListener('click', () => {
    _favOnly = !_favOnly;
    btn.classList.toggle('active', _favOnly);
    loadContacts(document.getElementById('contacts-search')?.value || '');
  });
  document.getElementById('contacts-bday-btn')?.addEventListener('click', showBirthdays);
  document.getElementById('contacts-groups-btn')?.addEventListener('click', showGroups);
  document.getElementById('contacts-dups-btn')?.addEventListener('click', showDuplicates);
  window._contactsCardDav = showCardDav;   // opened from the contacts settings cog (7b)
}

async function showCardDav() {
  const list = document.getElementById('contacts-list');
  const st = await fetch('/api/carddav/status').then(r => r.json()).catch(() => ({}));
  const ival = st.interval || 'off';
  const IV = [['off', t('contacts.sync_manual')], ['hourly', t('contacts.sync_hourly')], ['daily', t('contacts.sync_daily')]];
  list.innerHTML = `
    <div class="contacts-bday-head">${t('contacts.carddav_sync')} <button class="btn ic-btn-lbl" id="cdav-back" style="margin-left:8px">${_si('chevron-left')} ${t('contacts.back')}</button></div>
    <div class="carddav-panel">
      <div class="carddav-status ${st.connected ? 'on' : ''}" id="cdav-status">${st.connected ? `${_si('check')} ${_esc(t('contacts.connected_as', { name: st.username }))}` : t('contacts.not_connected')}</div>
      <p class="carddav-help">${t('contacts.carddav_help')}</p>
      <div class="carddav-actions">
        <button class="btn" id="cdav-connect">${st.connected ? t('contacts.reconnect') : t('contacts.connect')}</button>
        <button class="btn" id="cdav-sync"${st.connected ? '' : ' disabled'}>${t('contacts.sync_now')}</button>
        ${st.connected ? `<button class="btn danger" id="cdav-disconnect">${t('contacts.disconnect')}</button>` : ''}
      </div>
      <div class="carddav-field">
        <label>${t('contacts.auto_sync')}</label>
        <div class="seg seg-sm" id="cdav-interval">${IV.map(([v, l]) => `<button type="button" class="seg-opt${ival === v ? ' active' : ''}" data-val="${v}">${l}</button>`).join('')}</div>
      </div>
      <div class="carddav-result" id="cdav-result"></div>
    </div>`;
  document.getElementById('cdav-interval').querySelectorAll('.seg-opt').forEach(o =>
    o.addEventListener('click', async () => {
      document.querySelectorAll('#cdav-interval .seg-opt').forEach(x => x.classList.toggle('active', x === o));
      await fetch('/api/carddav/interval', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ interval: o.dataset.val }) });
    }));
  document.getElementById('cdav-back').addEventListener('click', () => loadContacts());
  document.getElementById('cdav-connect').addEventListener('click', async () => {
    const res = await _dlgFields(t('contacts.connect_title'), [
      { id: 'url', label: t('contacts.server_url'), value: st.url || '' },
      { id: 'username', label: t('contacts.username'), value: st.username || '' },
      { id: 'password', label: t('contacts.password'), value: '' },
    ]);
    if (!res) return;
    await fetch('/api/carddav/connect', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(res) });
    toast(t('common.saved'), 'success'); showCardDav();
  });
  document.getElementById('cdav-sync')?.addEventListener('click', async () => {
    const out = document.getElementById('cdav-result');
    out.textContent = t('contacts.syncing');
    try {
      const d = await fetch('/api/carddav/sync', { method: 'POST' }).then(r => r.json());
      out.textContent = d.error ? t('contacts.sync_error', { error: d.error }) : t('contacts.sync_done', { pulled: d.pulled, pushed: d.pushed });
      if (!d.error) loadContacts();
    } catch { out.textContent = t('contacts.sync_failed'); }
  });
  document.getElementById('cdav-disconnect')?.addEventListener('click', async () => {
    await fetch('/api/carddav/disconnect', { method: 'POST' });
    showCardDav();
  });
}

async function showBirthdays() {
  const list = document.getElementById('contacts-list');
  if (!list) return;
  const rows = await fetch('/api/contacts/birthdays?days=60').then(r => r.json()).catch(() => []);
  if (!rows.length) { list.innerHTML = `<div class="page-empty">${t('contacts.no_birthdays')}</div>`; return; }
  list.innerHTML = `<div class="contacts-bday-head">${t('contacts.upcoming_birthdays')}</div>` + rows.map(b => {
    const when = b.days_until === 0 ? t('contacts.today_bang') : (b.days_until === 1 ? t('contacts.tomorrow') : tp('contacts.in_days', b.days_until));
    return `<div class="settings-list-row contact-item"><span class="row-name">${_si('cake')} ${_esc(b.name)}</span><span class="row-meta">${_esc(b.birthday)} · ${when}</span></div>`;
  }).join('');
}

function _avatarHtml(c, big) {
  const sz = big ? 'contact-av-lg' : 'contact-av';
  // cache-key on the contact's own version, not Date.now(), or every keystroke re-downloads every avatar
  if (c.avatar) return `<img class="${sz}" src="/api/contacts/${c.id}/avatar?v=${encodeURIComponent(c.updated_at || c.avatar)}" alt="">`;
  const init = (c.name || '?').trim()[0]?.toUpperCase() || '?';
  return `<span class="${sz} contact-av-ph">${_esc(init)}</span>`;
}

export async function loadContacts(q = '', fetcher = fetch) {
  _wire();
  const list = document.getElementById('contacts-list');
  if (!list) return;
  const load = ++_contactsLoad;
  try {
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (_favOnly) params.set('favorites', 'true');
    const response = await fetcher('/api/contacts' + (params.toString() ? '?' + params : ''));
    if (!response.ok) throw new Error('contacts unavailable');
    const contacts = await response.json();
    if (!Array.isArray(contacts)) throw new Error('invalid contacts response');
    if (load !== _contactsLoad) return;
    if (_contactEntry !== null && routeHistoryPosition() < _contactEntry) _contactEntry = null;
    if (!contacts.length) { list.innerHTML = `<div class="page-empty">${_favOnly ? t('contacts.no_favorites') : t('contacts.no_contacts')}</div>`; return; }
    list.innerHTML = contacts.map(c => `
      <div class="contact-item" data-id="${c.id}">
        <button class="contact-star${c.favorite ? ' on' : ''}" data-id="${c.id}" title="${_esc(t('contacts.favorite'))}">${_si(c.favorite ? 'star-fill' : 'star')}</button>
        ${_avatarHtml(c)}
        <div class="contact-rowmain">
          <span class="row-name">${_esc(c.name)}${c.is_me ? ` <span class="contact-me-badge">${t('contacts.me')}</span>` : ''}</span>
          <span class="row-meta">${_esc(c.email || c.phone || '')}${c.company ? ' · ' + _esc(c.company) : ''}</span>
        </div>
        <div class="contact-rowacts">
          <button class="act-btn" data-open="${c.id}">${t('common.open')}</button>
          <button class="act-btn danger" data-del="${c.id}">${t('contacts.del')}</button>
        </div>
      </div>`).join('');
    list.querySelectorAll('.contact-star').forEach(s => s.addEventListener('click', async () => {
      const on = !s.classList.contains('on');
      await fetch(`/api/contacts/${s.dataset.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ favorite: on }) });
      loadContacts(document.getElementById('contacts-search')?.value || '');
    }));
    list.querySelectorAll('[data-open]').forEach(b => b.addEventListener('click', () => openContact(b.dataset.open)));
    list.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', () => delContact(b.dataset.del)));
    if (_returnTo && (!document.activeElement || document.activeElement === document.body)) list.querySelector(`[data-open="${CSS.escape(_returnTo)}"]`)?.focus();
    _returnTo = null;
  } catch {
    if (load !== _contactsLoad) return;
    list.innerHTML = `<div class="page-empty" role="alert">${t('contacts.load_failed')} <button class="btn" id="contacts-retry">${t('common.retry')}</button></div>`;
    list.querySelector('#contacts-retry').addEventListener('click', () => loadContacts(q, fetcher));
  }
}

async function delContact(id) {
  if (!await _dlgConfirm(t('contacts.delete_confirm'))) return;
  await fetch(`/api/contacts/${id}`, { method: 'DELETE' });
  loadContacts();
}

// on the contact's own entry, leaving is a real Back (the shell redraws the list), so the
// browser's Back never has to step over a list that's already showing
function leaveContact() {
  if (_contactEntry === null || _contactEntry !== routeHistoryPosition()) return false;
  history.back();
  return true;
}

const SCALARS = () => [['email', t('contacts.email')], ['phone', t('contacts.phone')], ['company', t('contacts.company')], ['title', t('contacts.title')],
  ['address', t('contacts.address')], ['birthday', t('contacts.birthday')], ['website', t('contacts.website')]];

async function openContact(id) {
  const [c, rels, all, evs] = await Promise.all([
    fetch('/api/contacts/' + id).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch(`/api/contacts/${id}/related`).then(r => r.ok ? r.json() : { related: [] }).then(j => j.related || []).catch(() => []),
    fetch('/api/contacts').then(r => r.ok ? r.json() : []).catch(() => []),
    fetch(`/api/contacts/${id}/events`).then(r => r.ok ? r.json() : { events: [] }).then(j => j.events || []).catch(() => []),
  ]);
  if (!c) return;
  const list = document.getElementById('contacts-list');
  const focusedId = list.contains(document.activeElement) ? document.activeElement.id : '';
  if (_contactEntry !== routeHistoryPosition()) {
    pushRouteUrl(location.pathname + location.search + location.hash);
    _contactEntry = routeHistoryPosition();
  }
  _returnTo = id;
  const mapLink = (c.address || '').trim()
    ? `<a class="contact-map" href="https://www.openstreetmap.org/search?query=${encodeURIComponent(c.address)}" target="_blank" rel="noopener">${_si('map-pin')} ${t('contacts.map')}</a>` : '';
  list.innerHTML = `
    <div class="contact-detail">
      <div class="contact-detail-head">
        <button class="btn ic-btn-lbl" id="cd-back">${_si('chevron-left')} ${t('contacts.back')}</button>
        <button type="button" class="contact-av-up" id="cd-avatar-btn" aria-label="${_esc(c.avatar ? t('contacts.change_photo') : t('contacts.set_photo'))}">${_avatarHtml(c, true)}<span class="contact-av-mark" aria-hidden="true">${_si('image')}</span></button><input type="file" id="cd-avatar" accept="image/*" hidden>
        <label class="contact-detail-name cd-field"><span>${t('contacts.name')}</span><input class="settings-input" id="cd-name" value="${_esc(c.name)}"></label>
        <button type="button" class="btn ic-btn-lbl" id="cd-me" aria-pressed="${!!c.is_me}">${c.is_me ? `${_si('check')} ${t('contacts.this_is_me')}` : t('contacts.set_as_me')}</button>
      </div>
      <div class="contact-scalars">
        ${SCALARS().map(([k, lbl]) => `<label class="cd-field"><span>${lbl}</span><input class="settings-input" data-k="${k}" value="${_esc(c[k] || '')}"></label>`).join('')}
        <label class="cd-field"><span>${t('contacts.notes')}</span><textarea class="settings-textarea" data-k="notes" rows="2">${_esc(c.notes || '')}</textarea></label>
      </div>
      ${mapLink}
      <div class="cd-section-title">${t('contacts.more_fields')}</div>
      <div id="cd-fields"></div>
      <div class="cd-addfield">
        <div class="settings-input custom-select" id="cd-fkind" data-options="${['email', 'phone', 'address', 'url', 'social', 'custom'].map(f => f + '|' + t('contacts.kind_' + f)).join(';')}" style="width:auto;min-width:90px"></div>
        <input class="settings-input" id="cd-flabel" placeholder="${_esc(t('contacts.label_placeholder'))}">
        <input class="settings-input" id="cd-fvalue" placeholder="${_esc(t('contacts.value_placeholder'))}">
        <button class="btn" id="cd-fadd">${t('contacts.add_field')}</button>
      </div>
      <div class="cd-section-title">${t('contacts.relationships')}</div>
      <div id="cd-rels"></div>
      <div class="cd-addrel" id="cd-addrel">
        <div class="settings-input custom-select" id="cd-relwho" data-placeholder="${_esc(t('contacts.contact'))}" style="min-width:120px"></div>
        <div class="settings-input custom-select" id="cd-relkind" data-options="${REL_KINDS.map(k => k + '|' + t('contacts.rel_' + k)).join(';')}" style="width:auto;min-width:90px"></div>
        <button class="btn" id="cd-reladd">${t('contacts.link')}</button>
      </div>
      <div id="cd-events"></div>
      <p class="contact-error" id="cd-error" role="alert" hidden></p>
      <div class="cd-actions"><button class="btn primary" id="cd-save">${t('common.save')}</button></div>
    </div>`;
  document.getElementById('cd-back').addEventListener('click', () => { if (!leaveContact()) loadContacts(); });
  document.getElementById('cd-me').addEventListener('click', async () => {
    await fetch(`/api/contacts/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ is_me: !c.is_me }) });
    openContact(id);
  });
  // the photo is a real button, so it's reachable by keyboard and looks like something to press
  document.getElementById('cd-avatar-btn').addEventListener('click', () => document.getElementById('cd-avatar').click());
  document.getElementById('cd-avatar').addEventListener('change', async e => {
    const f = e.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    await fetch(`/api/contacts/${id}/avatar`, { method: 'POST', body: fd });
    toast(t('contacts.photo_set'), 'success'); openContact(id);
  });
  let saving = false;
  document.getElementById('cd-save').addEventListener('click', async () => {
    if (saving) return;
    const detail = list.querySelector('.contact-detail');
    const error = detail.querySelector('#cd-error');
    const body = { name: detail.querySelector('#cd-name').value.trim() };
    detail.querySelectorAll('.contact-scalars [data-k]').forEach(el => { body[el.dataset.k] = el.value; });
    if (!body.name) { error.textContent = t('contacts.name_required'); error.hidden = false; return; }
    const controls = [...detail.querySelectorAll('input, textarea, button')].filter(el => !el.disabled);
    saving = true;
    error.hidden = true;
    controls.forEach(el => { el.disabled = true; });
    try {
      const response = await fetch(`/api/contacts/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
      await savedContact(response, body, id);
      toast(t('common.saved'), 'success');
      if (!leaveContact()) {
        await loadContacts();
        list.querySelector(`[data-open="${CSS.escape(id)}"]`)?.focus();
      }
    } catch {
      error.textContent = t('contacts.save_failed');
      error.hidden = false;
    } finally {
      saving = false;
      controls.forEach(el => { el.disabled = false; });
    }
  });
  initCustomDropdown(document.getElementById('cd-fkind'));
  document.getElementById('cd-fadd').addEventListener('click', async e => {
    const button = e.currentTarget;
    if (button.disabled) return;
    const labelInput = document.getElementById('cd-flabel');
    const valueInput = document.getElementById('cd-fvalue');
    const error = document.getElementById('cd-error');
    const fields = document.getElementById('cd-fields');
    const kind = getDropdownValue(document.getElementById('cd-fkind'));
    const label = labelInput.value.trim();
    const value = valueInput.value.trim();
    if (!value) { toast(t('contacts.value_needed'), ''); return; }
    button.disabled = labelInput.disabled = valueInput.disabled = true;
    error.hidden = true;
    try {
      const response = await fetch(`/api/contacts/${id}/fields`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ kind, label, value }) });
      const field = await response.json();
      if (!response.ok || !field || typeof field.id !== 'string' || !field.id || field.value !== value) throw new Error('field not saved');
      c.fields = [...(c.fields || []), field];
      if (fields.isConnected) renderFields(c);
      labelInput.value = valueInput.value = '';
    } catch {
      error.textContent = t('contacts.add_field_failed');
      error.hidden = false;
    } finally {
      button.disabled = labelInput.disabled = valueInput.disabled = false;
      valueInput.focus();
    }
  });
  renderFields(c);
  renderRels(id, rels);
  renderContactEvents(evs);

  // relationship picker: everyone except this contact + the ones already linked
  const linked = new Set(rels.map(r => r.id));
  const cands = all.filter(x => x.id !== id && !linked.has(x.id));
  const addRow = document.getElementById('cd-addrel');
  if (!cands.length) {
    addRow.innerHTML = `<div class="cd-nofields">${t('contacts.nothing_to_link')}</div>`;
  } else {
    populateDropdown(document.getElementById('cd-relwho'), cands.map(x => ({ value: x.id, label: x.name })));
    initCustomDropdown(document.getElementById('cd-relkind'));
    document.getElementById('cd-reladd').addEventListener('click', async () => {
      const who = getDropdownValue(document.getElementById('cd-relwho'));
      const kind = getDropdownValue(document.getElementById('cd-relkind'));
      if (!who) { toast(t('contacts.pick_contact'), ''); return; }
      const r = await fetch(`/api/contacts/${id}/links`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ to_id: who, kind }) });
      if (!r.ok) { toast(t('contacts.link_failed'), 'error'); return; }
      openContact(id);
    });
  }
  // the detail replaced whatever had focus: the same control after a redraw (set as me, a photo),
  // else back, the first stop of a freshly opened contact
  const active = document.activeElement;
  if (!active || active === document.body || !active.isConnected) (focusedId && document.getElementById(focusedId) || document.getElementById('cd-back'))?.focus();
}

function renderRels(cid, rels) {
  const box = document.getElementById('cd-rels');
  if (!box) return;
  if (!rels.length) { box.innerHTML = `<div class="cd-nofields">${t('contacts.no_relationships')}</div>`; return; }
  box.innerHTML = rels.map(r => `
    <div class="cd-rel-row">
      <button class="cd-rel-name" data-go="${r.id}">${_esc(r.name)}</button>
      <span class="cd-rel-kind">${_esc(r.kind ? _relLabel(r.kind) : t('contacts.linked'))}</span>
      <button class="cd-field-x" data-unlink="${r.id}" title="${_esc(t('common.remove'))}" aria-label="${_esc(t('contacts.remove_link', { name: r.name }))}">${_si('close')}</button>
    </div>`).join('');
  box.querySelectorAll('[data-go]').forEach(b => b.addEventListener('click', () => openContact(b.dataset.go)));
  box.querySelectorAll('[data-unlink]').forEach(b => b.addEventListener('click', async () => {
    await fetch(`/api/contacts/${cid}/links/${b.dataset.unlink}`, { method: 'DELETE' });
    openContact(cid);
  }));
}

const _rsvpLabel = status => ({ invited: t('contacts.rsvp_invited'), accepted: t('common.yes'), declined: t('common.no'), tentative: t('contacts.rsvp_maybe') })[status];

// 4a CRM-lite — shared calendar events: upcoming first, then a few recent past ones (dimmed)
function renderContactEvents(events) {
  const box = document.getElementById('cd-events');
  if (!box) return;
  if (!events.length) { box.innerHTML = ''; return; }   // keep the card clean when there's nothing
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const upcoming = [], past = [];
  for (const e of events) {
    const d = new Date(e.start_dt);
    (isNaN(d) || d >= today ? upcoming : past).push(e);
  }
  past.reverse();   // most recent first
  const row = e => {
    const d = new Date(e.start_dt);
    const isPast = !isNaN(d) && d < today;
    const dl = isNaN(d) ? _esc(e.start_dt || '')
      : _esc(formatDate(d, { month: 'short', day: 'numeric', year: 'numeric' })
        + (e.all_day ? '' : ' ' + formatTime(d, { hour: 'numeric', minute: '2-digit' })));
    const rsvp = e.status ? `<span class="cd-ev-rsvp s-${_esc(e.status)}">${_rsvpLabel(e.status) || _esc(e.status)}</span>` : '';
    return `<div class="cd-ev-row${isPast ? ' past' : ''}"><span class="cd-ev-date">${dl}</span><span class="cd-ev-title">${_esc(e.title || t('contacts.untitled'))}</span>${rsvp}</div>`;
  };
  box.innerHTML = `<div class="cd-section-title">${t('contacts.shared_events')}</div>`
    + upcoming.map(row).join('') + past.slice(0, 5).map(row).join('');
}

function renderFields(c) {
  const box = document.getElementById('cd-fields');
  if (!box) return;
  if (!c.fields?.length) { box.innerHTML = `<div class="cd-nofields">${t('contacts.no_fields')}</div>`; return; }
  box.innerHTML = c.fields.map(f => `
    <div class="cd-field-row" data-id="${f.id}">
      <span class="cd-field-kind">${_esc(f.kind)}${f.label ? ' · ' + _esc(f.label) : ''}</span>
      <span class="cd-field-val">${_esc(f.value)}</span>
      <button class="cd-field-x" data-del="${f.id}" aria-label="${_esc(t('contacts.remove_field', { kind: f.kind }))}">${_si('close')}</button>
    </div>`).join('');
  box.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', async () => {
    await fetch(`/api/contacts/${c.id}/fields/${b.dataset.del}`, { method: 'DELETE' });
    openContact(c.id);
  }));
}

async function showGroups() {
  const list = document.getElementById('contacts-list');
  const groups = await fetch('/api/contacts/groups').then(r => r.json()).catch(() => []);
  list.innerHTML = `
    <div class="contacts-bday-head">${t('contacts.groups')} <button class="btn" id="cg-add" style="margin-left:8px">${_si('plus')} ${t('contacts.group')}</button> <button class="btn ic-btn-lbl" id="cg-back">${_si('chevron-left')} ${t('contacts.back')}</button></div>
    <div id="cg-list">${groups.length ? '' : `<div class="page-empty">${t('contacts.no_groups')}</div>`}</div>`;
  document.getElementById('cg-back').addEventListener('click', () => loadContacts());
  document.getElementById('cg-add').addEventListener('click', addGroup);
  const cg = document.getElementById('cg-list');
  // fetch every group's members in parallel instead of one serialized round-trip per group
  const memberLists = await Promise.all(groups.map(g =>
    fetch(`/api/contacts/groups/${g.id}/members`).then(r => r.json()).catch(() => [])));
  groups.forEach((g, gi) => {
    const members = memberLists[gi];
    const div = document.createElement('div');
    div.className = 'settings-list-row';
    div.innerHTML = `<span class="row-name">${_esc(g.name)}${g.smart ? ` <span class="contact-me-badge">${t('contacts.smart')}</span>` : ''}</span>
      <span class="row-meta">${tp('contacts.members', members.length)}${g.rule_tag ? ' · #' + _esc(g.rule_tag) : ''}${g.rule_company ? ' · ' + _esc(g.rule_company) : ''}</span>
      <button class="act-btn danger" data-del="${g.id}">${t('contacts.del')}</button>`;
    div.querySelector('[data-del]').addEventListener('click', async () => {
      await fetch(`/api/contacts/groups/${g.id}`, { method: 'DELETE' }); showGroups();
    });
    cg.appendChild(div);
  });
}

async function addGroup() {
  const name = await _dlgPrompt('', '', { title: t('contacts.new_group'), label: t('contacts.group_name'), confirmLabel: t('common.next') });
  if (!name?.trim()) return;
  const tag = await _dlgPrompt('', '', { title: t('contacts.new_group'), label: t('contacts.group_tag_label'), hint: t('contacts.group_tag_hint'), confirmLabel: t('contacts.create_group') });
  const body = { name: name.trim() };
  if (tag?.trim()) { body.smart = true; body.rule_tag = tag.trim(); }
  await fetch('/api/contacts/groups', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  showGroups();
}

async function showDuplicates() {
  const list = document.getElementById('contacts-list');
  const clusters = await fetch('/api/contacts/duplicates').then(r => r.json()).catch(() => []);
  list.innerHTML = `<div class="contacts-bday-head">${t('contacts.possible_duplicates')} <button class="btn ic-btn-lbl" id="cdup-back" style="margin-left:8px">${_si('chevron-left')} ${t('contacts.back')}</button></div>`
    + (clusters.length ? '' : `<div class="page-empty">${t('contacts.no_duplicates')}</div>`)
    + clusters.map((cl, i) => `
      <div class="dup-cluster" data-i="${i}">
        ${cl.contacts.map(c => `<div class="dup-row"><span class="row-name">${_esc(c.name)}</span><span class="row-meta">${_esc(c.email || c.phone || '')}</span></div>`).join('')}
        <button class="btn" data-merge="${i}">${t('contacts.merge_these')}</button>
      </div>`).join('');
  document.getElementById('cdup-back').addEventListener('click', () => loadContacts());
  list.querySelectorAll('[data-merge]').forEach(b => b.addEventListener('click', async () => {
    const cl = clusters[Number(b.dataset.merge)];
    if (!cl) return;
    const primary = cl.contacts[0].id;
    for (const o of cl.contacts.slice(1)) {  // merge the WHOLE cluster, not just the first pair
      await fetch('/api/contacts/merge', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ primary_id: primary, other_id: o.id }) });
    }
    toast(t('contacts.merged'), 'success'); showDuplicates();
  }));
}

async function savedContact(response, expected, id = '') {
  const contact = await response.json();
  if (!response.ok || !contact || typeof contact.id !== 'string' || !contact.id
      || (id && contact.id !== id) || Object.entries(expected).some(([key, value]) => contact[key] !== value)) {
    throw new Error('contact save not confirmed');
  }
  return contact;
}

export async function addContact() {
  if (_creatingContact) return;
  const inputs = ['contact-name', 'contact-email', 'contact-phone'].map(id => document.getElementById(id));
  const [name, email, phone] = inputs.map(el => el.value.trim());
  const error = document.getElementById('contact-add-error');
  if (!name) { error.textContent = t('contacts.name_required'); error.hidden = false; inputs[0].focus(); return; }
  const button = document.getElementById('contact-add-btn');
  _creatingContact = true;
  error.hidden = true;
  button.disabled = true;
  inputs.forEach(el => { el.disabled = true; });
  try {
    const body = { name, email, phone };
    const response = await fetch('/api/contacts', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    const contact = await savedContact(response, body);
    inputs.forEach(el => { el.value = ''; });
    toast(t('contacts.contact_added'), 'success');
    await loadContacts();
    document.querySelector(`[data-open="${CSS.escape(contact.id)}"]`)?.focus();
  } catch {
    error.textContent = t('contacts.add_failed');
    error.hidden = false;
  } finally {
    _creatingContact = false;
    button.disabled = false;
    inputs.forEach(el => { el.disabled = false; });
  }
}

window._delContact = delContact;
window._editContact = openContact;

function _esc(s = '') {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

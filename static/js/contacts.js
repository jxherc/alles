import { toast } from './util.js';
import { confirm as _dlgConfirm, prompt as _dlgPrompt, fields as _dlgFields } from './dialog.js';
import { initCustomDropdown, getDropdownValue, populateDropdown } from './dropdown.js';

// 4a - typed relationship kinds (mirrors services/contacts_graph _INVERSE)
const REL_KINDS = ['friend', 'colleague', 'spouse', 'partner', 'sibling', 'parent', 'child', 'manager', 'report', 'mentor', 'mentee'];

let _favOnly = false;
let _wired = false;
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
  const IV = [['off', 'manual'], ['hourly', 'hourly'], ['daily', 'daily']];
  list.innerHTML = `
    <div class="contacts-bday-head">CardDAV sync <button class="btn ic-btn-lbl" id="cdav-back" style="font-size:.66rem;margin-left:8px">${_si('chevron-left')} contacts</button></div>
    <div class="carddav-panel">
      <div class="carddav-status ${st.connected ? 'on' : ''}" id="cdav-status">${st.connected ? `${_si('check')} connected as ${_esc(st.username)}` : 'not connected'}</div>
      <p class="carddav-help">two-way sync with iCloud, Google, or any CardDAV address book. enter your server URL + an app-specific password to connect.</p>
      <div class="carddav-actions">
        <button class="btn" id="cdav-connect">${st.connected ? 'reconnect' : 'connect'}</button>
        <button class="btn" id="cdav-sync"${st.connected ? '' : ' disabled'}>sync now</button>
        ${st.connected ? '<button class="btn danger" id="cdav-disconnect">disconnect</button>' : ''}
      </div>
      <div class="carddav-field">
        <label>auto-sync</label>
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
    const res = await _dlgFields('connect to CardDAV', [
      { id: 'url', label: 'server url (addressbook URL)', value: st.url || '' },
      { id: 'username', label: 'username', value: st.username || '' },
      { id: 'password', label: 'password / app-specific password', value: '' },
    ]);
    if (!res) return;
    await fetch('/api/carddav/connect', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(res) });
    toast('saved', 'success'); showCardDav();
  });
  document.getElementById('cdav-sync')?.addEventListener('click', async () => {
    const out = document.getElementById('cdav-result');
    out.textContent = 'syncing…';
    try {
      const d = await fetch('/api/carddav/sync', { method: 'POST' }).then(r => r.json());
      out.textContent = d.error ? `error: ${d.error}` : `pulled ${d.pulled}, pushed ${d.pushed}`;
      if (!d.error) loadContacts();
    } catch { out.textContent = 'sync failed'; }
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
  if (!rows.length) { list.innerHTML = '<div class="page-empty">no birthdays in the next 60 days</div>'; return; }
  list.innerHTML = `<div class="contacts-bday-head">upcoming birthdays</div>` + rows.map(b => {
    const when = b.days_until === 0 ? 'today!' : (b.days_until === 1 ? 'tomorrow' : `in ${b.days_until} days`);
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

export async function loadContacts(q = '') {
  _wire();
  const list = document.getElementById('contacts-list');
  if (!list) return;
  try {
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (_favOnly) params.set('favorites', 'true');
    const contacts = await fetch('/api/contacts' + (params.toString() ? '?' + params : '')).then(r => r.json());
    if (!contacts.length) { list.innerHTML = `<div class="page-empty">${_favOnly ? 'no favorites' : 'no contacts'}</div>`; return; }
    list.innerHTML = contacts.map(c => `
      <div class="contact-item" data-id="${c.id}">
        <button class="contact-star${c.favorite ? ' on' : ''}" data-id="${c.id}" title="favorite">${_si(c.favorite ? 'star-fill' : 'star')}</button>
        ${_avatarHtml(c)}
        <div class="contact-rowmain">
          <span class="row-name">${_esc(c.name)}${c.is_me ? ' <span class="contact-me-badge">me</span>' : ''}</span>
          <span class="row-meta">${_esc(c.email || c.phone || '')}${c.company ? ' · ' + _esc(c.company) : ''}</span>
        </div>
        <div class="contact-rowacts">
          <button class="act-btn" data-open="${c.id}">open</button>
          <button class="act-btn danger" data-del="${c.id}">del</button>
        </div>
      </div>`).join('');
    list.querySelectorAll('.contact-star').forEach(s => s.addEventListener('click', async () => {
      const on = !s.classList.contains('on');
      await fetch(`/api/contacts/${s.dataset.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ favorite: on }) });
      loadContacts(document.getElementById('contacts-search')?.value || '');
    }));
    list.querySelectorAll('[data-open]').forEach(b => b.addEventListener('click', () => openContact(b.dataset.open)));
    list.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', () => delContact(b.dataset.del)));
  } catch {
    list.innerHTML = '<div class="page-empty">failed to load</div>';
  }
}

async function delContact(id) {
  if (!await _dlgConfirm('delete contact?')) return;
  await fetch(`/api/contacts/${id}`, { method: 'DELETE' });
  loadContacts();
}

const SCALARS = [['email', 'email'], ['phone', 'phone'], ['company', 'company'], ['title', 'title'],
  ['address', 'address'], ['birthday', 'birthday (YYYY-MM-DD)'], ['website', 'website']];

async function openContact(id) {
  const [c, rels, all] = await Promise.all([
    fetch('/api/contacts/' + id).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch(`/api/contacts/${id}/related`).then(r => r.ok ? r.json() : { related: [] }).then(j => j.related || []).catch(() => []),
    fetch('/api/contacts').then(r => r.ok ? r.json() : []).catch(() => []),
  ]);
  if (!c) return;
  const list = document.getElementById('contacts-list');
  const mapLink = (c.address || '').trim()
    ? `<a class="contact-map" href="https://www.openstreetmap.org/search?query=${encodeURIComponent(c.address)}" target="_blank" rel="noopener">${_si('map-pin')} map</a>` : '';
  list.innerHTML = `
    <div class="contact-detail">
      <div class="contact-detail-head">
        <button class="btn ic-btn-lbl" id="cd-back">${_si('chevron-left')} contacts</button>
        <label class="contact-av-up" title="set photo">${_avatarHtml(c, true)}<input type="file" id="cd-avatar" accept="image/*" hidden></label>
        <div class="contact-detail-name"><input class="settings-input" id="cd-name" value="${_esc(c.name)}"></div>
        <button class="btn ic-btn-lbl${c.is_me ? ' primary' : ''}" id="cd-me">${c.is_me ? `${_si('check')} this is me` : 'set as me'}</button>
      </div>
      <div class="contact-scalars">
        ${SCALARS.map(([k, lbl]) => `<label class="cd-field"><span>${lbl}</span><input class="settings-input" data-k="${k}" value="${_esc(c[k] || '')}"></label>`).join('')}
        <label class="cd-field"><span>notes</span><textarea class="settings-textarea" data-k="notes" rows="2">${_esc(c.notes || '')}</textarea></label>
      </div>
      ${mapLink}
      <div class="cd-section-title">more fields</div>
      <div id="cd-fields"></div>
      <div class="cd-addfield">
        <div class="settings-input custom-select" id="cd-fkind" data-options="email|email;phone|phone;address|address;url|url;social|social;custom|custom" style="width:auto;min-width:90px"></div>
        <input class="settings-input" id="cd-flabel" placeholder="label (home/work…)">
        <input class="settings-input" id="cd-fvalue" placeholder="value">
        <button class="btn" id="cd-fadd">add field</button>
      </div>
      <div class="cd-section-title">relationships</div>
      <div id="cd-rels"></div>
      <div class="cd-addrel" id="cd-addrel">
        <div class="settings-input custom-select" id="cd-relwho" data-placeholder="contact" style="min-width:120px"></div>
        <div class="settings-input custom-select" id="cd-relkind" data-options="${REL_KINDS.map(k => k + '|' + k).join(';')}" style="width:auto;min-width:90px"></div>
        <button class="btn" id="cd-reladd">link</button>
      </div>
      <div class="cd-actions"><button class="btn primary" id="cd-save">save</button></div>
    </div>`;
  document.getElementById('cd-back').addEventListener('click', () => loadContacts());
  document.getElementById('cd-me').addEventListener('click', async () => {
    await fetch(`/api/contacts/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ is_me: !c.is_me }) });
    openContact(id);
  });
  document.getElementById('cd-avatar').addEventListener('change', async e => {
    const f = e.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    await fetch(`/api/contacts/${id}/avatar`, { method: 'POST', body: fd });
    toast('photo set', 'success'); openContact(id);
  });
  document.getElementById('cd-save').addEventListener('click', async () => {
    const body = { name: document.getElementById('cd-name').value.trim() };
    document.querySelectorAll('.contact-scalars [data-k]').forEach(el => { body[el.dataset.k] = el.value; });
    await fetch(`/api/contacts/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    toast('saved', 'success'); loadContacts();
  });
  initCustomDropdown(document.getElementById('cd-fkind'));
  document.getElementById('cd-fadd').addEventListener('click', async () => {
    const kind = getDropdownValue(document.getElementById('cd-fkind'));
    const label = document.getElementById('cd-flabel').value.trim();
    const value = document.getElementById('cd-fvalue').value.trim();
    if (!value) { toast('value needed', ''); return; }
    await fetch(`/api/contacts/${id}/fields`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ kind, label, value }) });
    openContact(id);
  });
  renderFields(c);
  renderRels(id, rels);

  // relationship picker: everyone except this contact + the ones already linked
  const linked = new Set(rels.map(r => r.id));
  const cands = all.filter(x => x.id !== id && !linked.has(x.id));
  const addRow = document.getElementById('cd-addrel');
  if (!cands.length) {
    addRow.innerHTML = '<div class="cd-nofields">add more contacts to link them</div>';
  } else {
    populateDropdown(document.getElementById('cd-relwho'), cands.map(x => ({ value: x.id, label: x.name })));
    initCustomDropdown(document.getElementById('cd-relkind'));
    document.getElementById('cd-reladd').addEventListener('click', async () => {
      const who = getDropdownValue(document.getElementById('cd-relwho'));
      const kind = getDropdownValue(document.getElementById('cd-relkind'));
      if (!who) { toast('pick a contact', ''); return; }
      const r = await fetch(`/api/contacts/${id}/links`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ to_id: who, kind }) });
      if (!r.ok) { toast('link failed', 'error'); return; }
      openContact(id);
    });
  }
}

function renderRels(cid, rels) {
  const box = document.getElementById('cd-rels');
  if (!box) return;
  if (!rels.length) { box.innerHTML = '<div class="cd-nofields">no relationships yet</div>'; return; }
  box.innerHTML = rels.map(r => `
    <div class="cd-rel-row">
      <button class="cd-rel-name" data-go="${r.id}">${_esc(r.name)}</button>
      <span class="cd-rel-kind">${_esc(r.kind || 'linked')}</span>
      <button class="cd-field-x" data-unlink="${r.id}" title="remove">×</button>
    </div>`).join('');
  box.querySelectorAll('[data-go]').forEach(b => b.addEventListener('click', () => openContact(b.dataset.go)));
  box.querySelectorAll('[data-unlink]').forEach(b => b.addEventListener('click', async () => {
    await fetch(`/api/contacts/${cid}/links/${b.dataset.unlink}`, { method: 'DELETE' });
    openContact(cid);
  }));
}

function renderFields(c) {
  const box = document.getElementById('cd-fields');
  if (!box) return;
  if (!c.fields?.length) { box.innerHTML = '<div class="cd-nofields">no extra fields yet</div>'; return; }
  box.innerHTML = c.fields.map(f => `
    <div class="cd-field-row" data-id="${f.id}">
      <span class="cd-field-kind">${_esc(f.kind)}${f.label ? ' · ' + _esc(f.label) : ''}</span>
      <span class="cd-field-val">${_esc(f.value)}</span>
      <button class="cd-field-x" data-del="${f.id}">×</button>
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
    <div class="contacts-bday-head">groups <button class="btn" id="cg-add" style="font-size:.66rem;margin-left:8px">+ group</button> <button class="btn ic-btn-lbl" id="cg-back" style="font-size:.66rem">${_si('chevron-left')} contacts</button></div>
    <div id="cg-list">${groups.length ? '' : '<div class="page-empty">no groups</div>'}</div>`;
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
    div.innerHTML = `<span class="row-name">${_esc(g.name)}${g.smart ? ' <span class="contact-me-badge">smart</span>' : ''}</span>
      <span class="row-meta">${members.length} member${members.length === 1 ? '' : 's'}${g.rule_tag ? ' · #' + _esc(g.rule_tag) : ''}${g.rule_company ? ' · ' + _esc(g.rule_company) : ''}</span>
      <button class="act-btn danger" data-del="${g.id}">del</button>`;
    div.querySelector('[data-del]').addEventListener('click', async () => {
      await fetch(`/api/contacts/groups/${g.id}`, { method: 'DELETE' }); showGroups();
    });
    cg.appendChild(div);
  });
}

async function addGroup() {
  const name = await _dlgPrompt('group name:');
  if (!name?.trim()) return;
  const tag = await _dlgPrompt('smart rule — tag to auto-include (blank for a manual group):', '');
  const body = { name: name.trim() };
  if (tag?.trim()) { body.smart = true; body.rule_tag = tag.trim(); }
  await fetch('/api/contacts/groups', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  showGroups();
}

async function showDuplicates() {
  const list = document.getElementById('contacts-list');
  const clusters = await fetch('/api/contacts/duplicates').then(r => r.json()).catch(() => []);
  list.innerHTML = `<div class="contacts-bday-head">possible duplicates <button class="btn ic-btn-lbl" id="cdup-back" style="font-size:.66rem;margin-left:8px">${_si('chevron-left')} contacts</button></div>`
    + (clusters.length ? '' : '<div class="page-empty">no duplicates found</div>')
    + clusters.map((cl, i) => `
      <div class="dup-cluster" data-i="${i}">
        ${cl.contacts.map(c => `<div class="dup-row"><span class="row-name">${_esc(c.name)}</span><span class="row-meta">${_esc(c.email || c.phone || '')}</span></div>`).join('')}
        <button class="btn" data-merge="${i}">merge these</button>
      </div>`).join('');
  document.getElementById('cdup-back').addEventListener('click', () => loadContacts());
  list.querySelectorAll('[data-merge]').forEach(b => b.addEventListener('click', async () => {
    const cl = clusters[Number(b.dataset.merge)];
    if (!cl) return;
    const primary = cl.contacts[0].id;
    for (const o of cl.contacts.slice(1)) {  // merge the WHOLE cluster, not just the first pair
      await fetch('/api/contacts/merge', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ primary_id: primary, other_id: o.id }) });
    }
    toast('merged', 'success'); showDuplicates();
  }));
}

export async function addContact() {
  const name = document.getElementById('contact-name')?.value.trim();
  const email = document.getElementById('contact-email')?.value.trim();
  const phone = document.getElementById('contact-phone')?.value.trim();
  if (!name) { toast('name required', 'error'); return; }
  await fetch('/api/contacts', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name, email, phone }) });
  ['contact-name', 'contact-email', 'contact-phone'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  toast('contact added', 'success');
  await loadContacts();
}

window._delContact = delContact;
window._editContact = openContact;

function _esc(s = '') {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

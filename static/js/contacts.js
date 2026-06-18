import { toast } from './util.js';
import { confirm as _dlgConfirm, fields as _dlgFields } from './dialog.js';

let _favOnly = false;
let _wiredFav = false;
function _wireFav() {
  if (_wiredFav) return; _wiredFav = true;
  const btn = document.getElementById('contacts-fav-filter');
  btn?.addEventListener('click', () => {
    _favOnly = !_favOnly;
    btn.classList.toggle('active', _favOnly);
    loadContacts(document.getElementById('contacts-search')?.value || '');
  });
  document.getElementById('contacts-bday-btn')?.addEventListener('click', showBirthdays);
}

async function showBirthdays() {
  const list = document.getElementById('contacts-list');
  if (!list) return;
  const rows = await fetch('/api/contacts/birthdays?days=60').then(r => r.json()).catch(() => []);
  if (!rows.length) { list.innerHTML = '<div class="page-empty">no birthdays in the next 60 days</div>'; return; }
  list.innerHTML = `<div class="contacts-bday-head">upcoming birthdays</div>` + rows.map(b => {
    const when = b.days_until === 0 ? 'today!' : (b.days_until === 1 ? 'tomorrow' : `in ${b.days_until} days`);
    return `<div class="settings-list-row contact-item"><span class="row-name">🎂 ${_esc(b.name)}</span><span class="row-meta">${_esc(b.birthday)} · ${when}</span></div>`;
  }).join('');
}

export async function loadContacts(q = '') {
  _wireFav();
  const list = document.getElementById('contacts-list');
  if (!list) return;
  try {
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (_favOnly) params.set('favorites', 'true');
    const url = '/api/contacts' + (params.toString() ? '?' + params : '');
    const contacts = await fetch(url).then(r => r.json());
    if (!contacts.length) { list.innerHTML = `<div class="page-empty">${_favOnly ? 'no favorites' : 'no contacts'}</div>`; return; }
    list.innerHTML = contacts.map(c => `
      <div class="settings-list-row contact-item" data-id="${c.id}">
        <button class="contact-star${c.favorite ? ' on' : ''}" data-id="${c.id}" title="favorite">${c.favorite ? '★' : '☆'}</button>
        <span class="row-name">${_esc(c.name)}</span>
        <span class="row-meta">${_esc(c.email || c.phone || '')}${c.company ? ' · ' + _esc(c.company) : ''}</span>
        <button class="act-btn" onclick="window._editContact('${c.id}')">edit</button>
        <button class="act-btn danger" onclick="window._delContact('${c.id}')">del</button>
      </div>`).join('');
    list.querySelectorAll('.contact-star').forEach(s => s.addEventListener('click', async () => {
      const on = !s.classList.contains('on');
      await fetch(`/api/contacts/${s.dataset.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ favorite: on }) });
      loadContacts(document.getElementById('contacts-search')?.value || '');
    }));
  } catch (e) {
    list.innerHTML = '<div class="page-empty">failed to load</div>';
  }
}

export async function addContact() {
  const name  = document.getElementById('contact-name')?.value.trim();
  const email = document.getElementById('contact-email')?.value.trim();
  const phone = document.getElementById('contact-phone')?.value.trim();
  if (!name) { toast('name required', 'error'); return; }
  await fetch('/api/contacts', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name, email, phone }),
  });
  ['contact-name','contact-email','contact-phone'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  toast('contact added', 'success');
  await loadContacts();
}

window._delContact = async id => {
  if (!await _dlgConfirm('delete contact?')) return;
  await fetch(`/api/contacts/${id}`, { method: 'DELETE' });
  loadContacts();
};

window._editContact = async id => {
  const r = await fetch(`/api/contacts?q=`).then(r => r.json());
  const c = r.find(x => x.id === id);
  if (!c) return;
  const res = await _dlgFields('edit contact', [
    { id: 'name',  label: 'name',  value: c.name  || '' },
    { id: 'email', label: 'email', value: c.email || '' },
    { id: 'phone', label: 'phone', value: c.phone || '' },
    { id: 'company', label: 'company', value: c.company || '' },
    { id: 'title', label: 'title', value: c.title || '' },
    { id: 'address', label: 'address', value: c.address || '' },
    { id: 'birthday', label: 'birthday (YYYY-MM-DD)', value: c.birthday || '' },
    { id: 'website', label: 'website', value: c.website || '' },
    { id: 'notes', label: 'notes', value: c.notes || '' },
  ]);
  if (!res) return;
  await fetch(`/api/contacts/${id}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(res),
  });
  loadContacts();
};

function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

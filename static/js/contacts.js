import { toast } from './util.js';
import { confirm as _dlgConfirm, fields as _dlgFields } from './dialog.js';

export async function loadContacts(q = '') {
  const list = document.getElementById('contacts-list');
  if (!list) return;
  try {
    const url = q ? `/api/contacts?q=${encodeURIComponent(q)}` : '/api/contacts';
    const contacts = await fetch(url).then(r => r.json());
    if (!contacts.length) { list.innerHTML = '<div class="page-empty">no contacts</div>'; return; }
    list.innerHTML = contacts.map(c => `
      <div class="settings-list-row contact-item" data-id="${c.id}">
        <span class="row-name">${_esc(c.name)}</span>
        <span class="row-meta">${_esc(c.email || c.phone || '')}${c.company ? ' · ' + _esc(c.company) : ''}</span>
        <button class="act-btn" onclick="window._editContact('${c.id}')">edit</button>
        <button class="act-btn danger" onclick="window._delContact('${c.id}')">del</button>
      </div>`).join('');
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

import { fields } from './dialog.js';
import { saveNote, showNoteRecovery } from './note_capture.js';
import { recordTarget, withRecordTarget } from './recordlinks.js';
import { singleHost, urlForApp } from './subdomain.js?v=237';
import { t } from './i18n.js';

let creating = false;
const host = () => document.getElementById('read-note-recovery');
const entry = () => document.getElementById('read-note') || document.getElementById('read-q');

export function readingSourceUrl(item) {
  const target = recordTarget('read', item.id, '', item.content_hash);
  if (!target?.hash) throw new Error(t('read.note_source_unconfirmed'));
  const base = singleHost() ? new URL('/', location.href) : new URL(urlForApp('library'));
  base.searchParams.set('view', 'read');
  const url = withRecordTarget(base, target);
  return singleHost() ? url.pathname + url.search : url.href;
}

export function readingNoteText(item, note) {
  if (!note.trim()) throw new Error(t('read.note_empty'));
  const title = String(item.title || 'saved article').replace(/\s+/g, ' ').replace(/[\\`*_{}\[\]()#+.!<>$~|=-]/g, '\\$&');
  return `${note}\n\nsource: [${title}](${readingSourceUrl(item)})\n`;
}

async function openNote(path) {
  if (!(await window._openSearchResult?.('note', path))) throw new Error(t('read.note_open_failed'));
}

function noteSaved(result, _text, focus = false) {
  const target = host();
  if (!target) return;
  target.dataset.savedNoteRequest = result.request_id;
  const status = document.createElement('p'); status.setAttribute('role', 'status'); status.textContent = t('read.saved_named', { name: result.path });
  const open = document.createElement('button'); open.type = 'button'; open.className = 'btn note-saved-open'; open.textContent = t('read.open_note');
  open.onclick = async () => {
    try { await openNote(result.path); }
    catch (error) { status.textContent = error.message; }
  };
  target.replaceChildren(status, open);
  if (focus && target.getClientRects().length) open.focus();
}

export async function loadReadingNoteRecovery() {
  const target = host();
  if (target) await showNoteRecovery(target, noteSaved, openNote, entry);
}

export async function takeReadingNote(item) {
  if (creating) return;
  creating = true;
  document.body.classList.add('reading-note-open');
  const source = { id: item.id, title: item.title, content_hash: item.content_hash };
  const title = String(item.title || t('read.note_default_name')).replace(/[\\/:*?"<>|#\[\]]+/g, ' ').trim().slice(0, 80) || t('read.note_default_name');
  let saved;
  try {
    await fields(t('read.note_from', { title: source.title }), [
      { id: 'name', label: t('read.note_name'), value: `${title}.md` },
      { id: 'note', label: t('read.note_label'), multiline: true },
    ], { submit: async value => {
      const path = value.name.trim();
      if (!path) throw new Error(t('read.note_name_required'));
      saved = await saveNote(readingNoteText(source, value.note), path, { preserveContent: true });
    } });
    if (saved) noteSaved(saved, '', true);
  } finally {
    creating = false;
    document.body.classList.remove('reading-note-open');
    await loadReadingNoteRecovery();
  }
}

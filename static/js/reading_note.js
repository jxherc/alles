import { fields } from './dialog.js';
import { saveNote, showNoteRecovery } from './note_capture.js';
import { recordTarget, withRecordTarget } from './recordlinks.js';
import { singleHost, urlForApp } from './subdomain.js?v=237';

let creating = false;
const host = () => document.getElementById('read-note-recovery');
const entry = () => document.getElementById('read-note') || document.getElementById('read-q');

export function readingSourceUrl(item) {
  const target = recordTarget('read', item.id, '', item.content_hash);
  if (!target?.hash) throw new Error('article source could not be confirmed; reopen it before taking a note');
  const base = singleHost() ? new URL('/', location.href) : new URL(urlForApp('library'));
  base.searchParams.set('view', 'read');
  const url = withRecordTarget(base, target);
  return singleHost() ? url.pathname + url.search : url.href;
}

export function readingNoteText(item, note) {
  if (!note.trim()) throw new Error('write a note before saving');
  const title = String(item.title || 'saved article').replace(/\s+/g, ' ').replace(/[\\`*_{}\[\]()#+.!<>$~|=-]/g, '\\$&');
  return `${note}\n\nsource: [${title}](${readingSourceUrl(item)})\n`;
}

async function openNote(path) {
  if (!(await window._openSearchResult?.('note', path))) throw new Error('could not open the saved note; try again');
}

function noteSaved(result, _text, focus = false) {
  const target = host();
  if (!target) return;
  target.dataset.savedNoteRequest = result.request_id;
  const status = document.createElement('p'); status.setAttribute('role', 'status'); status.textContent = `saved ${result.path}`;
  const open = document.createElement('button'); open.type = 'button'; open.className = 'btn note-saved-open'; open.textContent = 'open note';
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
  const title = String(item.title || 'reading note').replace(/[\\/:*?"<>|#\[\]]+/g, ' ').trim().slice(0, 80) || 'reading note';
  let saved;
  try {
    await fields(`note from ${source.title}`, [
      { id: 'name', label: 'note name', value: `${title}.md` },
      { id: 'note', label: 'note', multiline: true },
    ], { submit: async value => {
      const path = value.name.trim();
      if (!path) throw new Error('enter a note name');
      saved = await saveNote(readingNoteText(source, value.note), path, { preserveContent: true });
    } });
    if (saved) noteSaved(saved, '', true);
  } finally {
    creating = false;
    document.body.classList.remove('reading-note-open');
    await loadReadingNoteRecovery();
  }
}

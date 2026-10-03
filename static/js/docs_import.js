import { saveNote, showNoteRecovery } from './note_capture.js';

const MAX_BYTES = 8 * 1024 * 1024;
const $ = id => document.getElementById(id);
let wired = false;
let hooks;
let preview = null;
let controller = null;
let generation = 0;
let saving = false;
let entryButton = null;
const entry = () => [entryButton, $('docs-import-btn'), $('docs-empty-import')].find(button => button?.getClientRects().length);

function status(message) { $('docs-import-status').textContent = message; }
function lock(value) {
  for (const id of ['docs-import-choose', 'docs-import-name', 'docs-import-save', 'docs-import-close']) $(id).disabled = value;
  $('docs-import-save').disabled = value || !preview;
  $('docs-import-name').disabled = value || !preview;
}

function clearPreview() {
  ++generation; controller?.abort(); preview = null;
  $('docs-import-preview').textContent = ''; $('docs-import-name').value = '';
  status('nothing is saved until you choose import');
  $('docs-import-panel').hidden = true;
  lock(false);
}

async function openSaved(path) {
  if (!(await hooks.open(path))) throw new Error('could not open the saved document; try again');
}

function saved(result, text, restoreFocus = true, pendingBody = null) {
  const host = $('docs-import-recovery');
  restoreFocus ||= host.contains(document.activeElement);
  host.replaceChildren();
  host.dataset.savedNoteRequest = result.request_id;
  const message = document.createElement('p'); message.setAttribute('role', 'status');
  message.textContent = `saved ${result.path}`;
  const open = document.createElement('button'); open.type = 'button'; open.className = 'btn note-saved-open'; open.textContent = 'open saved document';
  open.onclick = async () => {
    try { await openSaved(result.path); }
    catch (error) { message.textContent = error.message; }
  };
  host.append(message, open);
  if (preview?.content === text && pendingBody?.content === preview.content && pendingBody?.path === $('docs-import-name').value.trim()) {
    restoreFocus ||= $('docs-import-panel').contains(document.activeElement);
    clearPreview();
  }
  void hooks.refresh();
  if (restoreFocus && host.getClientRects().length) open.focus();
}

async function recovery() {
  await showNoteRecovery($('docs-import-recovery'), saved, openSaved, entry);
}

async function chooseFile(file) {
  if (!file || saving) return;
  controller?.abort();
  controller = new AbortController();
  const run = ++generation;
  const focusBefore = document.activeElement;
  preview = null; lock(false);
  $('docs-import-preview').textContent = '';
  $('docs-import-name').value = '';
  if (file.size > MAX_BYTES) { status('choose a file smaller than 8 MiB'); return; }
  status(`reading ${file.name}…`);
  const form = new FormData(); form.append('file', file);
  try {
    const response = await fetch('/api/vault-md/import-preview', { method: 'POST', body: form, signal: controller.signal });
    const data = await response.json();
    if (run !== generation) return;
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'could not read this file; try again');
    if (typeof data.content !== 'string' || !data.content.trim() || typeof data.name !== 'string') throw new Error('no readable text found; nothing was saved');
    preview = data;
    $('docs-import-name').value = data.name + '.md';
    $('docs-import-preview').textContent = data.content;
    status(data.warning || 'review the text and name, then import. nothing has been saved yet.');
    lock(false);
    if ((document.activeElement === focusBefore || document.activeElement === document.body) && $('docs-import-panel').getClientRects().length) $('docs-import-name').focus();
  } catch (error) {
    if (run !== generation) return;
    status(error.name === 'AbortError' ? 'reading cancelled; nothing was saved' : error.message);
  }
}

async function accept() {
  if (!preview || saving) return;
  const path = $('docs-import-name').value.trim();
  if (!path || !/\.md$/i.test(path)) { status('enter a document name ending in .md'); $('docs-import-name').focus(); return; }
  const focusBefore = document.activeElement;
  saving = true; lock(true); status('saving document…');
  try {
    const result = await saveNote(preview.content, path, { preserveContent: true });
    saved(result, preview.content, document.activeElement === focusBefore || document.activeElement === document.body, { path, content: preview.content });
  } catch (error) { status(`${error.message}; your preview is kept`); }
  finally { saving = false; lock(false); await recovery(); }
}

export function initDocumentImport(options) {
  hooks = options;
  if (!wired) {
    wired = true;
    for (const id of ['docs-import-btn', 'docs-empty-import']) $(id).addEventListener('click', async event => {
      if (saving) return;
      entryButton = event.currentTarget;
      const button = entryButton;
      const focusBefore = document.activeElement;
      const run = generation;
      if (!(await hooks.prepare()) || saving || run !== generation || !button.getClientRects().length) return;
      hooks.show();
      $('docs-import-panel').hidden = false;
      if (document.activeElement === focusBefore || document.activeElement === document.body) $('docs-import-choose').focus();
      await recovery();
    });
    $('docs-import-choose').addEventListener('click', () => $('docs-import-file').click());
    $('docs-import-file').addEventListener('change', event => {
      const file = event.target.files?.[0]; event.target.value = '';
      void chooseFile(file);
    });
    $('docs-import-save').addEventListener('click', accept);
    $('docs-import-close').addEventListener('click', () => {
      if (saving) return;
      clearPreview(); entry()?.focus();
    });
  }
  void recovery();
}

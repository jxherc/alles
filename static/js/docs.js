// Docs is a viewer first. Obsidian is the primary editor; Alles exposes the same
// Markdown file through a local CodeMirror 6 editor only after the owner chooses Edit.
import { mdToHtml, enhanceMarkdown, toast } from './util.js';
import { loadNotes } from './notes.js';

let _section = 'docs';
let _cur = null;
let _doc = null;
let _draft = null;
let _tree = null;
let _editor = null;
let _editorFactory = null;
let _mode = 'view';
let _editView = 'visual';
let _dirty = false;
let _syncing = false;
let _wired = false;
let _es = null;
let _deepLinked = false;
let _draftTimer = 0;
let _largeDraftFlush = null;
let _persistedDraftPath = null;
let _persistedDraftRevision = -1;
let _persistedDraftHash = '';
let _documentWrites = Promise.resolve();
let _revertedDraftDeletion = null;
let _editRevision = 0;
let _editBaseHash = '';
let _openGeneration = 0;
let _dialogResolve = null;
let _dialogFocus = null;
let _visualFrontmatter = '';
let _fetcher = fetch;
const DOCS_NAV_STATE_KEY = 'alles.docs.nav.collapsed.v1';
const DRAFT_RECOVERY_KEY = 'alles.docs.draft.recovery.v1';
const DRAFT_KEEPALIVE_BYTES = 48 * 1024;

function draftWriteSession() {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return uuid;
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) {
    globalThis.crypto.getRandomValues(bytes);
    return [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

const DRAFT_WRITE_SESSION = draftWriteSession();
const DRAFT_WRITE_GENERATION = Date.now();

function readEmergencyDraft(path = '') {
  if (!path) return null;
  try {
    const value = JSON.parse(
      globalThis.localStorage?.getItem(`${DRAFT_RECOVERY_KEY}:${encodeURIComponent(path)}`) || 'null',
    );
    if (
      !value
      || value.version !== 1
      || typeof value.path !== 'string'
      || typeof value.content !== 'string'
      || typeof value.base_hash !== 'string'
      || (path && value.path !== path)
    ) return null;
    return value;
  } catch {
    return null;
  }
}

function persistEmergencyDraft(body) {
  if (!body?.path) return false;
  try {
    globalThis.localStorage?.setItem(`${DRAFT_RECOVERY_KEY}:${encodeURIComponent(body.path)}`, JSON.stringify({
      version: 1,
      ...body,
      saved_at: new Date().toISOString(),
    }));
    return !!globalThis.localStorage;
  } catch {
    return false;
  }
}

function clearEmergencyDraft(path, writeSession = '', writeRevision = null) {
  const current = readEmergencyDraft(path);
  if (!current) return;
  if (writeSession && current.write_session !== writeSession) return;
  if (writeRevision !== null && current.write_revision !== writeRevision) return;
  try { globalThis.localStorage?.removeItem(`${DRAFT_RECOVERY_KEY}:${encodeURIComponent(path)}`); }
  catch { /* Storage can be disabled after the draft was written. */ }
}

function draftWriteBody() {
  if (!_dirty || !_cur || !_doc?.editable) return null;
  return {
    path: _cur,
    content: currentContent(),
    base_hash: _editBaseHash || _doc.hash || '',
    write_session: DRAFT_WRITE_SESSION,
    write_revision: _editRevision,
    write_generation: DRAFT_WRITE_GENERATION,
  };
}

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const stem = path => (path || '').split('/').pop().replace(/\.(md|markdown)$/i, '');
const setHidden = (el, hidden) => { if (el) el.hidden = !!hidden; };

const ICONS = Object.freeze({
  document: '<path d="M4.5 2.75h8l3 3v11.5h-11z"/><path d="M12.5 2.75v3h3"/>',
  folder: '<path d="M2.75 5.25h5l1.5 1.75h8v9.5H2.75z"/>',
  chevron: '<path d="m7 5 5 5-5 5"/>',
  restore: '<path d="M4 8a6 6 0 1 1 1 7M4 8V3M4 8h5"/>',
});

function navIcon(name) {
  return `<svg class="docs-nav-icon" viewBox="0 0 20 20" aria-hidden="true">${ICONS[name] || ICONS.document}</svg>`;
}

async function api(url, options = {}) {
  let response;
  try { response = await _fetcher(url, options); }
  catch { throw new Error('Alles could not reach the local server'); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.detail || data.message || 'request failed');
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

function jsonOptions(method, body) {
  return { method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) };
}

export function initDocs(initialSection = 'docs', fetcher = fetch) {
  _fetcher = fetcher;
  window._prepareDocsNavigation = prepareDocsNavigation;
  _wire();
  window._reloadDocs = async () => {
    await loadTree();
    if (_cur && !_dirty) await openNote(_cur, { quiet: true });
  };
  const section = ['docs', 'notes', 'journal'].includes(initialSection) ? initialSection : 'docs';
  const loads = Promise.all([loadTree(), loadTags(), showSection(section)]);
  _watch();
  const legacyDocumentPath = new URLSearchParams(location.search).get('doc');
  if (!_deepLinked && legacyDocumentPath) {
    _deepLinked = true;
    openLegacyDocumentDeepLink(legacyDocumentPath);
  } else if (!_deepLinked && location.hash.length > 1) {
    _deepLinked = true;
    openByName(decodeURIComponent(location.hash.slice(1)));
  }
  return loads;
}

async function openLegacyDocumentDeepLink(path) {
  if (!(await openNote(path))) return;
  const url = new URL(location.href);
  url.searchParams.delete('doc');
  url.searchParams.delete('doc_hash');
  history.replaceState(null, '', url.pathname + url.search + url.hash);
}

function _wire() {
  if (_wired) return;
  _wired = true;

  wireDocsNavGroups();

  document.querySelectorAll('#docs-sections [data-section]').forEach(button => {
    button.addEventListener('click', async () => {
      if (button.dataset.section === 'docs') openDocsHome();
      else await switchDocsSection(button.dataset.section);
    });
  });
  let searchTimer = 0;
  $('wiki-search')?.addEventListener('input', event => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => doSearch(event.target.value.trim()), 160);
  });

  $('wiki-new-btn')?.addEventListener('click', newDoc);
  $('wiki-empty-new')?.addEventListener('click', newDoc);
  $('wiki-folder-btn')?.addEventListener('click', newFolder);
  $('wiki-trash-btn')?.addEventListener('click', openTrash);
  $('wiki-rename-btn')?.addEventListener('click', renameCurrent);
  $('wiki-delete-btn')?.addEventListener('click', deleteCurrent);
  $('wiki-history-btn')?.addEventListener('click', showRevisions);
  $('wiki-edit-btn')?.addEventListener('click', () => enterEdit());
  $('wiki-save-btn')?.addEventListener('click', saveCurrent);
  $('wiki-done-btn')?.addEventListener('click', exitEdit);
  $('wiki-discard-btn')?.addEventListener('click', discardDraft);
  $('wiki-visual-btn')?.addEventListener('click', () => setEditView('visual'));
  $('wiki-source-btn')?.addEventListener('click', () => setEditView('source'));
  $('wiki-source')?.addEventListener('input', sourceChanged);
  $('wiki-obsidian-btn')?.addEventListener('click', () => openInObsidian(_cur));
  $('wiki-empty-obsidian')?.addEventListener('click', () => openInObsidian(''));
  $('wiki-tree-toggle')?.addEventListener('click', toggleNavigation);
  $('wiki-more-btn')?.addEventListener('click', toggleMoreMenu);

  $('wiki-ask-btn')?.addEventListener('click', () => {
    const panel = $('wiki-ask');
    setHidden(panel, !panel.hidden);
    if (!panel.hidden) $('wiki-ask-input')?.focus();
  });
  $('wiki-ask-close')?.addEventListener('click', () => setHidden($('wiki-ask'), true));
  $('wiki-ask-go')?.addEventListener('click', askAideAboutCurrent);
  $('wiki-ask-input')?.addEventListener('keydown', event => {
    if (event.key === 'Enter') askAideAboutCurrent();
  });

  $('wiki-preview')?.addEventListener('click', event => {
    const link = event.target.closest('a[href^="#wiki="]');
    if (!link) return;
    event.preventDefault();
    openByName(decodeURIComponent(link.getAttribute('href').slice(6)));
  });

  document.addEventListener('pointerdown', event => {
    const menu = $('wiki-more-menu');
    if (!menu || menu.hidden) return;
    if (!menu.contains(event.target) && !$('wiki-more-btn')?.contains(event.target)) closeMoreMenu();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      if (!$('docs-dialog')?.hidden) closeDialog({ action: 'cancel', value: '' });
      closeMoreMenu();
    }
  });
  addEventListener('pagehide', persistDraftOnPageHide);
  addEventListener('beforeunload', guardLargeDraftDeparture);
}

function readDocsNavState() {
  try { return JSON.parse(localStorage.getItem(DOCS_NAV_STATE_KEY) || '{}'); }
  catch { return {}; }
}

function applyDocsNavGroup(button, collapsed) {
  const panel = document.getElementById(button.getAttribute('aria-controls') || '');
  if (!panel) return;
  button.setAttribute('aria-expanded', String(!collapsed));
  panel.hidden = collapsed;
  button.closest('.docs-nav-section')?.classList.toggle('is-collapsed', collapsed);
}

function wireDocsNavGroups() {
  const state = readDocsNavState();
  document.querySelectorAll('[data-docs-collapse]').forEach(button => {
    const name = button.dataset.docsCollapse;
    applyDocsNavGroup(button, !!state[name]);
    button.addEventListener('click', () => {
      const collapsed = button.getAttribute('aria-expanded') === 'true';
      applyDocsNavGroup(button, collapsed);
      const next = readDocsNavState();
      next[name] = collapsed;
      localStorage.setItem(DOCS_NAV_STATE_KEY, JSON.stringify(next));
    });
  });
}

export async function prepareDocsNavigation() {
  return flushDraft();
}

async function switchDocsSection(section) {
  if (!(await flushDraft())) return false;
  showSection(section);
  return true;
}

function toggleNavigation() {
  const view = $('wiki-view');
  if (!view) return;
  const mobile = matchMedia('(max-width: 760px)').matches;
  if (mobile) view.classList.toggle('docs-nav-open');
  else view.classList.toggle('docs-nav-hidden');
  const visible = mobile ? view.classList.contains('docs-nav-open') : !view.classList.contains('docs-nav-hidden');
  $('wiki-tree-toggle')?.setAttribute('aria-expanded', String(visible));
}

async function openDocsHome() {
  ++_openGeneration;
  const draftSaved = await flushDraft();
  if (!draftSaved) return false;
  _cur = null;
  _doc = null;
  _draft = null;
  _editBaseHash = '';
  _dirty = false;
  _mode = 'view';
  destroyEditor();
  if (location.hash) history.replaceState(null, '', location.pathname + location.search);
  showSection('docs');
  renderShell();
  return true;
}

export function showSection(section) {
  const nextSection = ['notes', 'journal'].includes(section) ? section : 'docs';
  if (nextSection !== 'docs') ++_openGeneration;
  _section = nextSection;
  const view = $('wiki-view');
  if (view) view.dataset.docsSection = _section;
  if (matchMedia('(max-width: 760px)').matches) view?.classList.remove('docs-nav-open');
  document.querySelectorAll('#docs-sections [data-section]').forEach(button => {
    const active = button.dataset.section === _section;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  const journal = _section === 'journal';
  setHidden($('docs-reader-main'), journal);
  setHidden($('docs-journal-section'), !journal);
  setHidden($('journal-migrate'), !journal);
  setHidden($('wiki-trash-btn'), journal);

  if (journal) {
    setHidden($('docs-context-panel'), true);
    setHidden($('wiki-ask'), true);
    $('wiki-view')?.classList.remove('no-note', 'docs-nav-open');
    return import('./journal.js?v=253').then(module => module.initJournal());
  }

  if (_section === 'notes') {
    setHidden($('wiki-notes'), false);
    setHidden($('wiki-empty-state'), true);
    setHidden($('wiki-document'), true);
    setHidden($('docs-context-panel'), true);
    setHidden($('wiki-ask'), true);
    $('wiki-view')?.classList.remove('no-note');
    if ($('wiki-current')) $('wiki-current').textContent = 'notes';
    if ($('wiki-path')) $('wiki-path').textContent = 'quick notes in your local vault';
    return loadNotes(_fetcher);
  }
  setHidden($('wiki-notes'), true);
  renderShell();
}

function renderShell() {
  const hasDoc = !!(_cur && _doc);
  $('wiki-view')?.classList.toggle('no-note', !hasDoc);
  setHidden($('wiki-empty-state'), hasDoc);
  setHidden($('wiki-document'), !hasDoc);
  setHidden($('docs-context-panel'), !hasDoc);
  if (!hasDoc) {
    if ($('wiki-current')) $('wiki-current').textContent = 'your Obsidian vault';
    if ($('wiki-path')) $('wiki-path').textContent = 'local Markdown';
    if ($('wiki-stats')) $('wiki-stats').textContent = '';
    if ($('wiki-save-state')) $('wiki-save-state').textContent = '';
    setHidden($('wiki-ask'), true);
    return;
  }
  setHidden($('wiki-preview'), _mode === 'edit');
  setHidden($('wiki-editor'), _mode !== 'edit');
  if ($('wiki-current')) $('wiki-current').textContent = stem(_cur);
  if ($('wiki-path')) $('wiki-path').textContent = _cur;
  $('wiki-edit-btn').textContent = _mode === 'edit' ? 'editing' : 'edit';
  $('wiki-edit-btn').disabled = _mode === 'edit' || !_doc.editable;
  updateStats(currentContent());
  updateSaveState();
}

// External edits from Obsidian are safe to reload only when there is no local draft.
function _watch() {
  if (_es || typeof EventSource === 'undefined') return;
  try {
    _es = new EventSource('/api/vault-md/stream');
    _es.onmessage = async event => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }
      // The stream snapshots the vault when the connection is accepted. A file
      // can change after the initial tree request but before that snapshot, so
      // reconcile once on the server hello instead of silently missing it.
      if (data.hello) {
        if ($('wiki-view')?.style.display !== 'none') await loadTree();
        return;
      }
      const changed = [...(data.changed || []), ...(data.removed || [])];
      if (!changed.length || $('wiki-view')?.style.display === 'none') return;
      if (_section === 'notes') { window._reloadNotes?.(); return; }
      await loadTree();
      if (_section === 'journal') return;
      if (!_cur || !changed.includes(_cur)) return;
      if ((data.removed || []).includes(_cur)) {
        showInlineState('This file was removed outside Alles. Your local draft is still safe.', [
          { label: 'back to documents', action: openDocsHome },
        ]);
        return;
      }
      if (_dirty || _draft) {
        showInlineState('This file changed in Obsidian while a local draft was open.', [
          { label: 'compare copies', action: compareExternal },
          { label: 'use file from disk', action: useExternalCopy },
        ]);
        return;
      }
      await openNote(_cur, { quiet: true });
      setSaveState('updated from Obsidian');
    };
    _es.onerror = () => {};
  } catch {}
}

export async function loadTree() {
  try {
    _tree = await api('/api/vault-md/tree');
    renderTree(_tree.items || []);
    paintRecent(_tree.items || []);
  } catch (error) {
    const tree = $('wiki-tree');
    if (tree) tree.innerHTML = `<div class="docs-nav-empty">${esc(error.message)}</div>`;
  }
}

function renderTree(items) {
  const box = $('wiki-tree');
  if (!box) return;
  const renderKey = JSON.stringify([items, _cur]);
  if (box.dataset.renderKey === renderKey) return;
  const html = items.length
    ? items.map(rowHtml).join('')
    : '<div class="docs-nav-empty">no Markdown files yet</div>';
  box.innerHTML = html;
  box.dataset.renderKey = renderKey;
  wireTree(box);
}

function invalidateTreeRender(box = $('wiki-tree')) {
  if (box) delete box.dataset.renderKey;
}

function wireTree(box) {
  box.querySelectorAll('[data-file]').forEach(row => {
    row.addEventListener('click', () => openNote(row.dataset.file));
  });
  box.querySelectorAll('[data-dir]').forEach(button => {
    button.addEventListener('click', () => {
      const row = button.closest('.wiki-dir');
      row?.classList.toggle('open');
      button.setAttribute('aria-expanded', String(row?.classList.contains('open')));
    });
  });
}

function rowHtml(item) {
  if (item.type === 'dir') {
    return `<div class="wiki-dir">
      <button class="wiki-dir-head" type="button" data-dir="${esc(item.path)}" aria-expanded="false">
        <svg class="wiki-dir-chevron" viewBox="0 0 20 20" aria-hidden="true">${ICONS.chevron}</svg>
        ${navIcon('folder')}<span>${esc(item.name)}</span>
      </button>
      <div class="wiki-dir-kids">${(item.children || []).map(rowHtml).join('')}</div>
    </div>`;
  }
  return `<button class="wiki-file${_cur === item.path ? ' active' : ''}" type="button" data-file="${esc(item.path)}">
    ${navIcon('document')}<span class="wiki-row-label">${esc(item.name)}</span>
  </button>`;
}

function flatFiles(items, output = []) {
  for (const item of items) {
    if (item.type === 'dir') flatFiles(item.children || [], output);
    else output.push(item);
  }
  return output;
}

function paintRecent(items) {
  const recent = flatFiles(items).sort((a, b) => (b.mtime || 0) - (a.mtime || 0)).slice(0, 8);
  const recentKey = JSON.stringify(recent);
  const rail = $('docs-recent');
  if (rail) {
    const railHtml = recent.slice(0, 4).map(file => `
      <button class="docs-recent-item" type="button" data-file="${esc(file.path)}">
        ${navIcon('document')}<span>${esc(file.name)}</span>
      </button>`).join('') || '<div class="docs-nav-empty">nothing opened yet</div>';
    if (rail.dataset.renderKey !== recentKey) {
      rail.innerHTML = railHtml;
      rail.dataset.renderKey = recentKey;
      rail.querySelectorAll('[data-file]').forEach(row => row.addEventListener('click', () => openNote(row.dataset.file)));
    }
  }
  const grid = $('wiki-empty-recent');
  if (grid) {
    const gridHtml = recent.map(file => `
      <button class="docs-home-card" type="button" data-file="${esc(file.path)}">
        ${navIcon('document')}<span class="docs-home-card-copy"><span class="dhc-title">${esc(file.name)}</span><small>${esc(file.path)}</small></span>
      </button>`).join('') || '<div class="docs-home-empty">new documents will show up here</div>';
    if (grid.dataset.renderKey !== recentKey) {
      grid.innerHTML = gridHtml;
      grid.dataset.renderKey = recentKey;
      grid.querySelectorAll('[data-file]').forEach(row => row.addEventListener('click', () => openNote(row.dataset.file)));
    }
  }
}

function prepMarkdown(markdown) {
  let value = previewBody(markdown);
  value = value.replace(/!\[\[([^\]]+)\]\]/g, (match, raw) => {
    const name = raw.split('|')[0].trim();
    return `![${name}](/api/vault-md/raw?path=${encodeURIComponent(name)})`;
  });
  return value.replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]/g, (match, name, alias) =>
    `[${(alias || name).trim()}](#wiki=${encodeURIComponent(name.trim())})`);
}

// Frontmatter stays byte-for-byte in the source/editor, but the reader should not turn
// YAML metadata into an accidental paragraph. An unclosed block is ordinary content.
function previewBody(markdown) {
  return splitMarkdownDocument(markdown).body;
}

function splitMarkdownDocument(markdown) {
  const value = String(markdown || '');
  const match = value.match(/^\uFEFF?---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/);
  return match
    ? { frontmatter: match[0], body: value.slice(match[0].length) }
    : { frontmatter: '', body: value };
}

function renderPreview(markdown = currentContent()) {
  const preview = $('wiki-preview');
  if (!preview) return;
  preview.innerHTML = mdToHtml(prepMarkdown(markdown));
  enhanceMarkdown(preview);
}

export async function openNote(path, { quiet = false, draftFlushed = false } = {}) {
  if (!path) return false;
  const requestGeneration = ++_openGeneration;
  const departureRevision = _editRevision;
  if (_dirty && !draftFlushed && !(await flushDraft())) return false;
  if (requestGeneration !== _openGeneration) return false;
  try {
    const requestedPath = String(path);
    const openedDoc = await api('/api/vault-md/file?path=' + encodeURIComponent(requestedPath));
    if (!openedDoc.exists) throw new Error('That document no longer exists');
    const openedPath = openedDoc.path || requestedPath;
    const serverDraft = (
      await api('/api/vault-md/safety/draft?path=' + encodeURIComponent(openedPath))
    ).draft || null;
    const emergencyDraft = readEmergencyDraft(openedPath);
    const draftsMatch = Boolean(
      emergencyDraft && serverDraft && emergencyDraft.content === serverDraft.content
    );
    const sameWriteSession = Boolean(
      emergencyDraft?.write_session
      && emergencyDraft.write_session === serverDraft?.write_session
    );
    const emergencyRevision = Number(emergencyDraft?.write_revision ?? -1);
    const serverRevision = Number(serverDraft?.write_revision ?? -1);
    const emergencyIsNewer = sameWriteSession && emergencyRevision > serverRevision;
    const serverIsNewer = sameWriteSession && serverRevision > emergencyRevision;
    const draftsNeedOwnerChoice = Boolean(
      emergencyDraft && serverDraft && !draftsMatch && !emergencyIsNewer && !serverIsNewer
    );
    let openedDraft = emergencyDraft && (!serverDraft || emergencyIsNewer || draftsNeedOwnerChoice)
      ? emergencyDraft
      : serverDraft;
    let alternateServerDraft = draftsNeedOwnerChoice ? serverDraft : null;
    if (emergencyDraft && openedDraft !== emergencyDraft && (draftsMatch || serverIsNewer)) {
      clearEmergencyDraft(openedPath);
    }
    if (serverDraft?.content === openedDoc.content) {
      const cleanupQuery = new URLSearchParams({
        path: openedPath,
        expected_hash: serverDraft.draft_hash,
      });
      try {
        await api('/api/vault-md/safety/draft?' + cleanupQuery.toString(), {
          method: 'DELETE',
        });
      } catch {
        // This draft is byte-identical to the authoritative document. Cleanup is retryable
        // housekeeping and must not block opening content that already loaded successfully.
      }
      if (openedDraft === serverDraft) openedDraft = null;
      if (alternateServerDraft === serverDraft) alternateServerDraft = null;
    }
    if (emergencyDraft?.content === openedDoc.content) {
      clearEmergencyDraft(openedPath);
      if (openedDraft === emergencyDraft) openedDraft = null;
    }
    const backlinksState = await fetchBacklinks(openedPath);
    if (requestGeneration !== _openGeneration) return false;
    if (_dirty && _editRevision !== departureRevision && !(await flushDraft())) return false;
    if (requestGeneration !== _openGeneration) return false;
    _section = 'docs';
    _cur = openedPath;
    _doc = openedDoc;
    _draft = openedDraft;
    _persistedDraftPath = openedDraft?.draft_hash ? openedPath : null;
    _persistedDraftRevision = openedDraft?.draft_hash ? Number(openedDraft.write_revision ?? -1) : -1;
    _persistedDraftHash = openedDraft?.draft_hash || '';
    _editBaseHash = openedDraft?.base_hash || openedDoc.hash || '';
    _mode = 'view';
    _dirty = false;
    destroyEditor();
    renderPreview(_doc.content || '');
    showSection('docs');
    renderShell();
    renderBacklinks(backlinksState);
    updateActiveRows();
    renderFileDetail();
    if (!_doc.editable) {
      showInlineState('This file is not UTF-8, so Alles keeps it read-only. Open it in Obsidian or another editor.', []);
    } else if (_draft && alternateServerDraft) {
      showInlineState(
        'A browser recovery copy and a server draft both exist. Choose which one to continue.',
        [
          { label: 'resume browser copy', action: () => enterEdit(_draft.content) },
          {
            label: 'use server draft',
            action: () => {
              if (_cur !== openedPath) return;
              clearEmergencyDraft(openedPath);
              _draft = alternateServerDraft;
              _editBaseHash = _draft.base_hash || _doc.hash || '';
              enterEdit(_draft.content);
            },
          },
        ],
      );
    } else if (_draft) {
      const changedOutside = _draft.base_hash !== _doc.hash;
      showInlineState(
        changedOutside ? 'A local draft and the file on disk both changed.' : 'A private local draft is waiting.',
        [
          { label: 'resume draft', action: () => enterEdit(_draft.content) },
          ...(changedOutside ? [{ label: 'compare copies', action: compareExternal }] : []),
          { label: 'discard draft', action: discardDraft },
        ],
      );
    } else {
      hideInlineState();
    }
    if (!quiet) history.replaceState(null, '', location.pathname + location.search + '#' + encodeURIComponent(stem(_cur)));
    return true;
  } catch (error) {
    if (requestGeneration !== _openGeneration) return false;
    toast(error.message || 'could not open that document', 'error');
    return false;
  }
}

function updateActiveRows() {
  document.querySelectorAll('#wiki-tree [data-file], #docs-recent [data-file]').forEach(row => {
    row.classList.toggle('active', row.dataset.file === _cur);
  });
}

async function openByName(name) {
  try {
    const result = await api('/api/vault-md/search?q=' + encodeURIComponent(name));
    const hits = result.results || [];
    const hit = hits.find(item => String(item.name || '').toLowerCase() === name.toLowerCase()) || hits[0];
    if (hit) await openNote(hit.path);
    else toast(`"${name}" was not found`, '');
  } catch (error) { toast(error.message, 'error'); }
}

async function fetchBacklinks(path) {
  try {
    const result = await api('/api/vault-md/backlinks?name=' + encodeURIComponent(stem(path)));
    return { available: true, backlinks: result.backlinks || [] };
  } catch {
    return { available: false, backlinks: [] };
  }
}

function renderBacklinks({ available, backlinks }) {
  const box = $('wiki-backlinks');
  if (!box) return;
  if (!available) {
    box.innerHTML = '<div class="docs-context-empty">backlinks unavailable</div>';
    return;
  }
  box.innerHTML = backlinks.length
    ? backlinks.map(item => `<button type="button" data-file="${esc(item.path)}">${navIcon('document')}<span>${esc(item.name)}</span></button>`).join('')
    : '<div class="docs-context-empty">no links point here yet</div>';
  box.querySelectorAll('[data-file]').forEach(row => row.addEventListener('click', () => openNote(row.dataset.file)));
}

function renderFileDetail() {
  const box = $('docs-file-detail');
  if (!box || !_doc) return;
  box.innerHTML = `
    <div><span>path</span><strong>${esc(_cur)}</strong></div>
    <div><span>format</span><strong>Markdown</strong></div>
    <div><span>encoding</span><strong>${esc(_doc.encoding || 'UTF-8')}</strong></div>`;
}

function currentContent() {
  if (_mode === 'edit') {
    if (_editView === 'source') return $('wiki-source')?.value || '';
    return _editor ? _visualFrontmatter + _editor.getValue() : (_draft?.content ?? _doc?.content ?? '');
  }
  return _dirty ? (_draft?.content ?? _doc?.content ?? '') : (_doc?.content ?? '');
}

async function enterEdit(content = null) {
  if (!_doc?.editable) { toast('This file is read-only in Alles', 'error'); return; }
  const editPath = _cur;
  const editGeneration = _openGeneration;
  const value = content ?? _draft?.content ?? _doc.content ?? '';
  _editBaseHash = _draft?.base_hash || _doc.hash || '';
  _mode = 'edit';
  _editView = 'visual';
  _dirty = value !== (_doc.content || '') || !!_draft;
  renderShell();
  const ready = await ensureEditor(value, { path: editPath, generation: editGeneration });
  if (!ready) return;
  setEditView('visual');
  _editor?.focus();
}

async function ensureEditor(value, guard = null) {
  const parts = splitMarkdownDocument(value);
  _visualFrontmatter = parts.frontmatter;
  if (!_editorFactory) {
    const module = await import('../vendor/cm6.bundle.js');
    _editorFactory = module.createDocEditor;
  }
  if (guard && (guard.path !== _cur || guard.generation !== _openGeneration || _mode !== 'edit')) return false;
  if (_editor) {
    _syncing = true;
    _editor.setValue(parts.body);
    _syncing = false;
    if ($('wiki-source')) $('wiki-source').value = value;
    return true;
  }
  const host = $('wiki-live');
  if (!host) return false;
  host.replaceChildren();
  _editor = _editorFactory(host, {
    doc: parts.body,
    onChange: editorChanged,
    wikiComplete: async query => {
      const result = await api('/api/vault-md/names');
      return (result.names || []).filter(name => name.toLowerCase().includes(String(query || '').toLowerCase())).map(name => ({ name }));
    },
  });
  if ($('wiki-source')) $('wiki-source').value = value;
  return true;
}

function destroyEditor() {
  _editor?.destroy?.();
  _editor = null;
  $('wiki-live')?.replaceChildren();
}

function editorChanged(value) {
  if (_syncing) return;
  const wasDirty = _dirty;
  const fullValue = _visualFrontmatter + value;
  _dirty = fullValue !== (_doc?.content || '');
  _editRevision += 1;
  _draft = _dirty ? { path: _cur, content: fullValue, base_hash: _editBaseHash } : null;
  if ($('wiki-source') && $('wiki-source').value !== fullValue) $('wiki-source').value = fullValue;
  updateStats(fullValue);
  updateSaveState();
  if (wasDirty && !_dirty) {
    clearEmergencyDraft(_cur);
    queueRevertedDraftDeletion(_cur, _editRevision, _persistedDraftHash);
  } else scheduleDraft();
}

function sourceChanged() {
  if (_syncing) return;
  const wasDirty = _dirty;
  const value = $('wiki-source')?.value || '';
  _dirty = value !== (_doc?.content || '');
  _editRevision += 1;
  _draft = _dirty ? { path: _cur, content: value, base_hash: _editBaseHash } : null;
  const parts = splitMarkdownDocument(value);
  _visualFrontmatter = parts.frontmatter;
  if (_editor && _editor.getValue() !== parts.body) {
    _syncing = true;
    _editor.setValue(parts.body);
    _syncing = false;
  }
  updateStats(value);
  updateSaveState();
  if (wasDirty && !_dirty) {
    clearEmergencyDraft(_cur);
    queueRevertedDraftDeletion(_cur, _editRevision, _persistedDraftHash);
  } else scheduleDraft();
}

function setEditView(view) {
  _editView = view === 'source' ? 'source' : 'visual';
  const source = _editView === 'source';
  setHidden($('wiki-live'), source);
  setHidden($('wiki-source'), !source);
  $('wiki-visual-btn')?.setAttribute('aria-pressed', String(!source));
  $('wiki-source-btn')?.setAttribute('aria-pressed', String(source));
  if (source) $('wiki-source')?.focus();
  else _editor?.focus();
}

function exitEdit() {
  if (_mode !== 'edit') return;
  if (_dirty) {
    const content = currentContent();
    _draft = { path: _cur, content, base_hash: _editBaseHash };
    renderPreview(content);
    flushDraft();
  } else renderPreview(_doc.content || '');
  _mode = 'view';
  renderShell();
}

function scheduleDraft() {
  clearTimeout(_draftTimer);
  const body = draftWriteBody();
  if (!body) return;
  if (_revertedDraftDeletion?.path === _cur) _revertedDraftDeletion = null;
  const recoveredLocally = persistEmergencyDraft(body);
  if (new TextEncoder().encode(JSON.stringify(body)).byteLength > DRAFT_KEEPALIVE_BYTES) {
    startLargeDraftFlush();
    if (!recoveredLocally) setSaveState('large draft is still being secured locally', true);
    return;
  }
  _draftTimer = setTimeout(flushDraft, 450);
}

function startLargeDraftFlush() {
  if (_largeDraftFlush) return _largeDraftFlush;
  _largeDraftFlush = flushDraft().finally(() => { _largeDraftFlush = null; });
  return _largeDraftFlush;
}

function guardLargeDraftDeparture(event) {
  if (!_dirty || !_cur || !_doc?.editable) return;
  const body = { path: _cur, content: currentContent(), base_hash: _editBaseHash || _doc.hash || '' };
  const isLarge = new TextEncoder().encode(JSON.stringify(body)).byteLength > DRAFT_KEEPALIVE_BYTES;
  const isPersisted = _persistedDraftPath === _cur && _persistedDraftRevision === _editRevision;
  const emergency = readEmergencyDraft(_cur);
  const isRecovered = emergency?.write_session === DRAFT_WRITE_SESSION
    && emergency?.write_revision === _editRevision;
  if (!isLarge || isPersisted || isRecovered) return;
  startLargeDraftFlush();
  event.preventDefault();
  event.returnValue = '';
}

function persistDraftOnPageHide() {
  const body = draftWriteBody();
  if (!body) return;
  clearTimeout(_draftTimer);
  _draftTimer = 0;
  persistEmergencyDraft(body);
  if (new TextEncoder().encode(JSON.stringify(body)).byteLength > DRAFT_KEEPALIVE_BYTES) {
    startLargeDraftFlush();
    return;
  }
  _fetcher('/api/vault-md/safety/draft', {
    ...jsonOptions('PUT', body),
    keepalive: true,
  }).then(response => {
    if (response.ok) clearEmergencyDraft(body.path, body.write_session, body.write_revision);
  }).catch(() => {});
}

function queueDocumentWrite(operation) {
  const queued = _documentWrites.then(operation, operation);
  _documentWrites = queued.catch(() => {});
  return queued;
}

function queueRevertedDraftDeletion(path, revision, expectedHash) {
  clearTimeout(_draftTimer);
  _draftTimer = 0;
  if (!expectedHash || _persistedDraftPath !== path) return Promise.resolve(true);
  const marker = { path, revision, expectedHash, promise: null };
  _revertedDraftDeletion = marker;
  marker.promise = queueDocumentWrite(async () => {
    if (_cur !== path || _editRevision !== revision || _dirty) return;
    const query = new URLSearchParams({ path, expected_hash: expectedHash });
    await api('/api/vault-md/safety/draft?' + query.toString(), {
      method: 'DELETE',
    });
  }).then(() => {
    if (_revertedDraftDeletion === marker) _revertedDraftDeletion = null;
    if (_persistedDraftPath === path && _persistedDraftHash === expectedHash) {
      _persistedDraftPath = null;
      _persistedDraftRevision = -1;
      _persistedDraftHash = '';
    }
    if (_cur === path && _editRevision === revision && !_dirty) setSaveState('saved');
    return true;
  }).catch(error => {
    if (_revertedDraftDeletion === marker) marker.promise = null;
    if (_cur === path && _editRevision === revision && !_dirty) {
      setSaveState(error.message || 'stale draft could not be cleared', true);
    }
    return false;
  });
  return marker.promise;
}

async function deleteDraftSafely(path) {
  clearTimeout(_draftTimer);
  _draftTimer = 0;
  try {
    await queueDocumentWrite(async () => {
      let expectedHash = _persistedDraftPath === path ? _persistedDraftHash : '';
      if (!expectedHash) {
        const current = await api(
          '/api/vault-md/safety/draft?path=' + encodeURIComponent(path),
        );
        expectedHash = current?.draft?.draft_hash || '';
      }
      if (!expectedHash) return;
      const query = new URLSearchParams({ path, expected_hash: expectedHash });
      await api('/api/vault-md/safety/draft?' + query.toString(), { method: 'DELETE' });
      if (_persistedDraftPath === path && _persistedDraftHash === expectedHash) {
        _persistedDraftPath = null;
        _persistedDraftRevision = -1;
        _persistedDraftHash = '';
      }
    });
    return true;
  } catch (error) {
    if (_dirty) scheduleDraft();
    throw error;
  }
}

async function flushDraft() {
  clearTimeout(_draftTimer);
  _draftTimer = 0;
  if (!_dirty || !_cur || !_doc?.editable) {
    const cleanup = _revertedDraftDeletion;
    if (!cleanup || cleanup.path !== _cur || cleanup.revision !== _editRevision) return true;
    return cleanup.promise || queueRevertedDraftDeletion(cleanup.path, cleanup.revision, cleanup.expectedHash);
  }
  const path = _cur;
  const content = currentContent();
  const revision = _editRevision;
  const fallbackHash = _editBaseHash || _doc.hash;
  try {
    const savedDraft = await queueDocumentWrite(() => api(
      '/api/vault-md/safety/draft',
      jsonOptions('PUT', {
        path,
        content,
        base_hash: fallbackHash,
        write_session: DRAFT_WRITE_SESSION,
        write_revision: revision,
        write_generation: DRAFT_WRITE_GENERATION,
      }),
    ));
    if (_cur === path && _editRevision === revision && _dirty) {
      _draft = savedDraft;
      _persistedDraftPath = path;
      _persistedDraftRevision = revision;
      _persistedDraftHash = savedDraft.draft_hash || '';
      clearEmergencyDraft(path, DRAFT_WRITE_SESSION, revision);
      setSaveState('draft kept locally');
    }
    if (_cur === path && _editRevision !== revision && _dirty) return await flushDraft();
    return true;
  } catch (error) {
    if (_cur === path && _editRevision === revision) {
      setSaveState(error.message || 'draft could not be saved', true);
    }
    return false;
  }
}

async function saveCurrent() {
  if (!_cur || !_doc?.editable || !_dirty) return true;
  clearTimeout(_draftTimer);
  _draftTimer = 0;
  const path = _cur;
  const content = currentContent();
  const revision = _editRevision;
  const expectedHash = _editBaseHash || _doc.hash;
  $('wiki-save-btn').disabled = true;
  setSaveState('saving…');
  try {
    const result = await queueDocumentWrite(() => api(
      '/api/vault-md/safety/save',
      jsonOptions('POST', { path, content, expected_hash: expectedHash }),
    ));
    if (_cur !== path) return true;
    _doc = { ..._doc, ...result, content };
    _editBaseHash = result.hash || expectedHash;
    if (_editRevision === revision) {
      _draft = null;
      _dirty = false;
      clearEmergencyDraft(path, DRAFT_WRITE_SESSION, revision);
      renderPreview(content);
      hideInlineState();
      setSaveState('saved');
    } else {
      _dirty = true;
      if (_draft) _draft.base_hash = result.hash || expectedHash;
      setSaveState('new changes not saved');
    }
    await loadTree();
    renderFileDetail();
    if (_cur === path && _editRevision !== revision && _dirty) return await saveCurrent();
    return true;
  } catch (error) {
    if (error.status === 409 && error.data?.code === 'document_conflict') {
      showInlineState('The file changed in Obsidian. Alles preserved both copies.', [
        { label: 'compare copies', action: compareExternal },
        { label: 'use file from disk', action: useExternalCopy },
      ]);
      setSaveState('save paused · conflict', true);
    } else {
      setSaveState(error.message || 'save failed', true);
      toast(error.message || 'save failed', 'error');
    }
    return false;
  } finally { $('wiki-save-btn').disabled = false; }
}

async function discardDraft() {
  if (!_cur) return;
  const choice = await openDialog({
    title: 'discard local draft?',
    body: '<p>The Markdown file on disk will stay unchanged.</p>',
    actions: [
      { id: 'cancel', label: 'keep draft' },
      { id: 'discard', label: 'discard draft', danger: true },
    ],
  });
  if (choice.action !== 'discard') return;
  try { await deleteDraftSafely(_cur); }
  catch (error) { toast(error.message, 'error'); return; }
  _draft = null;
  _dirty = false;
  _editBaseHash = _doc.hash || '';
  clearEmergencyDraft(_cur);
  _mode = 'view';
  destroyEditor();
  renderPreview(_doc.content || '');
  hideInlineState();
  renderShell();
}

async function compareExternal() {
  if (!_cur || !_doc) return;
  const local = _draft?.content ?? currentContent();
  try {
    const comparison = await api('/api/vault-md/safety/compare', jsonOptions('POST', {
      path: _cur,
      content: local,
      expected_hash: _editBaseHash || _doc.hash,
    }));
    const diff = comparison.diff || 'The two copies are currently identical.';
    const choice = await openDialog({
      title: 'compare Markdown copies',
      body: `<p><b>file from disk</b> is shown with minus lines. <b>local draft</b> is shown with plus lines.</p><pre class="docs-diff">${esc(diff)}</pre>`,
      actions: [
        { id: 'keep', label: 'keep my draft' },
        { id: 'external', label: 'use file from disk' },
        { id: 'replace', label: 'replace file with my draft', danger: true },
      ],
    });
    if (choice.action === 'external') await useExternalCopy();
    if (choice.action === 'replace') {
      await replaceExternalWithDraft(local, comparison.current_hash);
    }
  } catch (error) { toast(error.message || 'comparison failed', 'error'); }
}

async function useExternalCopy() {
  if (!_cur) return;
  try {
    await deleteDraftSafely(_cur);
    _draft = null;
    _dirty = false;
    clearEmergencyDraft(_cur);
    await openNote(_cur, { quiet: true });
  } catch (error) { toast(error.message, 'error'); }
}

async function replaceExternalWithDraft(content, reviewedHash) {
  clearTimeout(_draftTimer);
  _draftTimer = 0;
  const path = _cur;
  const revision = _editRevision;
  try {
    const result = await queueDocumentWrite(() => api('/api/vault-md/safety/save', jsonOptions('POST', {
      path,
      content,
      expected_hash: reviewedHash,
    })));
    if (_cur !== path) return;
    _doc = { ..._doc, ...result, content };
    _editBaseHash = result.hash || reviewedHash;
    if (_editRevision === revision) {
      _draft = null;
      _dirty = false;
      clearEmergencyDraft(path, DRAFT_WRITE_SESSION, revision);
      renderPreview(content);
      hideInlineState();
      renderShell();
      setSaveState('saved · previous file kept in revisions');
    } else {
      _dirty = true;
      if (_draft) _draft.base_hash = result.hash || reviewedHash;
      setSaveState('new changes not saved');
      scheduleDraft();
    }
  } catch (error) {
    if (error.status === 409 && error.data?.code === 'document_conflict') {
      showInlineState('The file changed again. Review the newest copy before replacing it.', [
        { label: 'compare again', action: compareExternal },
        { label: 'use file from disk', action: useExternalCopy },
      ]);
      setSaveState('save paused · file changed again', true);
      return;
    }
    toast(error.message || 'replace failed', 'error');
  }
}

function updateStats(content) {
  const text = String(content || '');
  const words = (text.trim().match(/\S+/g) || []).length;
  const minutes = words ? Math.max(1, Math.ceil(words / 220)) : 0;
  if ($('wiki-stats')) $('wiki-stats').textContent = words ? `${words} words · ${minutes} min` : 'empty document';
}

function setSaveState(message, error = false) {
  const state = $('wiki-save-state');
  if (!state) return;
  state.textContent = message;
  state.classList.toggle('error', error);
}

function updateSaveState() {
  if (!_doc?.editable) setSaveState('read only');
  else if (_dirty) setSaveState('local draft · not saved');
  else setSaveState('saved');
  if ($('wiki-save-btn')) $('wiki-save-btn').disabled = !_dirty;
}

function showInlineState(message, actions = []) {
  const bar = $('wiki-inline-state');
  if (!bar) return;
  if ($('wiki-inline-message')) $('wiki-inline-message').textContent = message;
  const holder = $('wiki-inline-actions');
  if (holder) {
    holder.replaceChildren();
    for (const item of actions) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = item.label;
      button.addEventListener('click', item.action);
      holder.appendChild(button);
    }
  }
  bar.hidden = false;
}

function hideInlineState() { setHidden($('wiki-inline-state'), true); }

async function doSearch(query) {
  if (!query) { renderTree(_tree?.items || []); return; }
  const box = $('wiki-tree');
  invalidateTreeRender(box);
  try {
    const result = await api('/api/vault-md/grep?q=' + encodeURIComponent(query));
    const hits = result.results || [];
    box.innerHTML = hits.length
      ? hits.map(hit => `<button class="wiki-file docs-search-hit" type="button" data-file="${esc(hit.path)}">
          ${navIcon('document')}<span class="wiki-row-label"><b>${esc(hit.name)}</b>${hit.context ? `<small>${esc(hit.context)}</small>` : ''}</span>
        </button>`).join('')
      : '<div class="docs-nav-empty">no matches</div>';
    wireTree(box);
  } catch (error) { box.innerHTML = `<div class="docs-nav-empty">${esc(error.message)}</div>`; }
}

async function loadTags() {
  const box = $('wiki-tags');
  if (!box) return;
  try {
    const result = await api('/api/vault-md/tags');
    box.innerHTML = (result.tags || []).slice(0, 8).map(item =>
      `<button class="wiki-tag" type="button" data-tag="${esc(item.tag)}">#${esc(item.tag)} <span>${item.count}</span></button>`).join('');
    box.querySelectorAll('[data-tag]').forEach(button => button.addEventListener('click', () => filterByTag(button.dataset.tag)));
  } catch { box.replaceChildren(); }
}

async function filterByTag(tag) {
  const box = $('wiki-tree');
  invalidateTreeRender(box);
  try {
    const result = await api('/api/vault-md/tag?tag=' + encodeURIComponent(tag));
    box.innerHTML = `<button class="docs-tag-clear" type="button">#${esc(tag)} · clear</button>` +
      (result.notes || []).map(note => `<button class="wiki-file" type="button" data-file="${esc(note.path)}">${navIcon('document')}<span>${esc(note.name)}</span></button>`).join('');
    box.querySelector('.docs-tag-clear')?.addEventListener('click', () => renderTree(_tree?.items || []));
    wireTree(box);
  } catch (error) { toast(error.message, 'error'); }
}

async function askAideAboutCurrent() {
  const question = $('wiki-ask-input')?.value.trim();
  if (!question || !_doc || !_cur) return;
  if (_dirty && !(await saveCurrent())) return;
  setHidden($('wiki-ask'), true);
  window._askInChat?.(question, false, {
    kind: 'vault_document',
    path: _cur,
    expected_hash: _doc.hash,
  });
}

async function openInObsidian(path) {
  try {
    const suffix = path ? '?path=' + encodeURIComponent(path) : '';
    const result = await api('/api/vault-location' + suffix);
    if (result.obsidian) location.href = result.obsidian;
    else toast('Set an Obsidian vault in Docs settings first', 'error');
  } catch (error) { toast(error.message, 'error'); }
}

async function newDoc() {
  const answer = await promptText('new Markdown document', 'document name', '');
  if (answer.action !== 'confirm') return;
  const name = answer.value.trim();
  if (!name) { toast('Enter a document name', 'error'); return; }
  try {
    if (_dirty && !(await flushDraft())) return;
    const result = await api('/api/vault-md/file', jsonOptions('POST', { path: name, content: '' }));
    await loadTree();
    const opened = await openNote(result.path);
    if (!opened) return;
    await enterEdit('');
  } catch (error) { toast(error.message, 'error'); }
}

async function newFolder() {
  const answer = await promptText('new folder', 'folder name', '');
  if (answer.action !== 'confirm' || !answer.value.trim()) return;
  try {
    await api('/api/vault-md/folder', jsonOptions('POST', { path: answer.value.trim() }));
    await loadTree();
  } catch (error) { toast(error.message, 'error'); }
}

async function renameCurrent() {
  closeMoreMenu();
  if (!_cur) return;
  const answer = await promptText('rename document', 'new name', stem(_cur));
  if (answer.action !== 'confirm' || !answer.value.trim()) return;
  const directory = _cur.includes('/') ? _cur.slice(0, _cur.lastIndexOf('/') + 1) : '';
  try {
    if (_draft && !_dirty) {
      toast('resume or discard the saved draft before renaming', 'error');
      return;
    }
    if (_dirty && !(await saveCurrent())) return;
    const result = await api('/api/vault-md/rename', jsonOptions('POST', {
      path: _cur,
      new_path: directory + answer.value.trim(),
    }));
    _cur = result.path;
    await loadTree();
    await openNote(result.path, { quiet: true });
  } catch (error) { toast(error.message, 'error'); }
}

async function deleteCurrent() {
  closeMoreMenu();
  if (!_cur) return;
  const answer = await openDialog({
    title: `move "${esc(stem(_cur))}" to trash?`,
    body: '<p>You can restore it from Recently deleted.</p>',
    actions: [
      { id: 'cancel', label: 'cancel' },
      { id: 'delete', label: 'move to trash', danger: true },
    ],
  });
  if (answer.action !== 'delete') return;
  try {
    if (_draft && !_dirty) {
      toast('resume or discard the saved draft before deleting', 'error');
      return;
    }
    if (_dirty && !(await saveCurrent())) return;
    await api('/api/vault-md/file?path=' + encodeURIComponent(_cur), { method: 'DELETE' });
    await openDocsHome();
    await loadTree();
    toast('moved to trash', 'success');
  } catch (error) { toast(error.message, 'error'); }
}

async function openTrash() {
  try {
    const items = await api('/api/vault-md/trash');
    const box = $('wiki-tree');
    invalidateTreeRender(box);
    box.innerHTML = items.length
      ? items.map(item => `<div class="docs-trash-row" data-trash-id="${esc(item.id)}">
          ${navIcon('document')}<span>${esc(item.path)}</span>
          <button type="button" data-restore aria-label="restore ${esc(item.path)}">${navIcon('restore')}restore</button>
        </div>`).join('')
      : '<div class="docs-nav-empty">trash is empty</div>';
    box.querySelectorAll('[data-restore]').forEach(button => button.addEventListener('click', async () => {
      const row = button.closest('[data-trash-id]');
      try {
        const result = await api('/api/vault-md/trash/restore', jsonOptions('POST', { id: row.dataset.trashId }));
        await loadTree();
        if (result.restored) await openNote(result.restored);
      } catch (error) { toast(error.message, 'error'); }
    }));
  } catch (error) { toast(error.message, 'error'); }
}

async function showRevisions() {
  closeMoreMenu();
  if (!_cur) return;
  try {
    const result = await api('/api/vault-md/safety/revisions?path=' + encodeURIComponent(_cur));
    const revisions = result.revisions || [];
    const promise = openDialog({
      title: 'document revisions',
      body: revisions.length
        ? `<div class="docs-revision-list">${revisions.map(revision => `
            <button type="button" data-revision="${esc(revision.id)}">
              <span>${esc(revision.reason || 'before save')}</span><small>${esc(revision.created_at || revision.id)}</small>
            </button>`).join('')}</div>`
        : '<p>No earlier revisions yet. Alles creates one before every save.</p>',
      actions: [{ id: 'cancel', label: 'close' }],
    });
    $('docs-dialog-body')?.querySelectorAll('[data-revision]').forEach(button => {
      button.addEventListener('click', () => closeDialog({ action: 'restore', value: button.dataset.revision }));
    });
    const answer = await promise;
    if (answer.action !== 'restore') return;
    const confirm = await openDialog({
      title: 'restore this revision?',
      body: '<p>Alles will keep the current file as another revision first.</p>',
      actions: [{ id: 'cancel', label: 'cancel' }, { id: 'restore', label: 'restore revision' }],
    });
    if (confirm.action !== 'restore') return;
    await api('/api/vault-md/safety/revisions/restore', jsonOptions('POST', {
      path: _cur,
      revision_id: answer.value,
      expected_hash: _doc.hash,
    }));
    await openNote(_cur, { quiet: true });
    toast('revision restored', 'success');
  } catch (error) { toast(error.message, 'error'); }
}

function toggleMoreMenu() {
  const menu = $('wiki-more-menu');
  if (!menu) return;
  menu.hidden = !menu.hidden;
  $('wiki-more-btn')?.setAttribute('aria-expanded', String(!menu.hidden));
  if (!menu.hidden) menu.querySelector('button')?.focus();
}

function closeMoreMenu() {
  setHidden($('wiki-more-menu'), true);
  $('wiki-more-btn')?.setAttribute('aria-expanded', 'false');
}

function promptText(title, label, value) {
  return openDialog({
    title,
    body: `<label class="docs-dialog-field">${esc(label)}<input id="docs-dialog-input" value="${esc(value)}" autocomplete="off"></label>`,
    actions: [{ id: 'cancel', label: 'cancel' }, { id: 'confirm', label: 'continue' }],
    input: true,
  });
}

function openDialog({ title, body = '', actions = [], input = false }) {
  if (_dialogResolve) closeDialog({ action: 'cancel', value: '' });
  const layer = $('docs-dialog');
  _dialogFocus = document.activeElement;
  $('docs-dialog-title').textContent = title;
  $('docs-dialog-body').innerHTML = body;
  $('docs-dialog-error').textContent = '';
  const footer = $('docs-dialog-actions');
  footer.replaceChildren();
  const promise = new Promise(resolve => { _dialogResolve = resolve; });
  for (const action of actions) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = action.label;
    button.dataset.dialogAction = action.id;
    if (action.danger) button.classList.add('danger');
    button.addEventListener('click', () => closeDialog({
      action: action.id,
      value: input ? ($('docs-dialog-input')?.value || '') : '',
    }));
    footer.appendChild(button);
  }
  layer.hidden = false;
  layer.addEventListener('keydown', trapDialogFocus);
  requestAnimationFrame(() => (input ? $('docs-dialog-input') : footer.querySelector('button'))?.focus());
  return promise;
}

function closeDialog(result) {
  const layer = $('docs-dialog');
  if (!layer || layer.hidden) return;
  layer.hidden = true;
  layer.removeEventListener('keydown', trapDialogFocus);
  const resolve = _dialogResolve;
  _dialogResolve = null;
  resolve?.(result);
  _dialogFocus?.focus?.();
  _dialogFocus = null;
}

function setDialogError(message) {
  if ($('docs-dialog-error')) $('docs-dialog-error').textContent = message;
}

function trapDialogFocus(event) {
  if (event.key !== 'Tab') return;
  const focusable = [...$('docs-dialog').querySelectorAll('button:not([disabled]), input:not([disabled])')];
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}

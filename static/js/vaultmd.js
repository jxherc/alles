// docs: file tree + a CodeMirror live-preview editor + rendered preview, with
// [[wikilinks]], backlinks, embeds, tags, graph, outline, history.
//
// modes (mode button cycles): live = CodeMirror WYSIWYG (markdown symbols hidden,
// styled inline, symbols reveal on the cursor's line) · source = raw markdown
// textarea · preview = fully rendered. CodeMirror edits plain markdown text
// directly (no lossy round-trip), so a save can never corrupt the file.
import { mdToHtml, toast, enhanceMarkdown, api } from './util.js';
import { prompt as dlgPrompt, confirm as dlgConfirm } from './dialog.js';

let _cur = null;
let _saveT = 0;
let _inited = false;
let _sortMode = localStorage.getItem('docs-sort') || 'name';   // 'name' | 'recent'

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const _syncEmpty = () => $('wiki-view')?.classList.toggle('no-note', !_cur);
const _docsVisible = () => { const v = $('wiki-view'); return v && v.style.display !== 'none' && v.offsetParent !== null; };

// pinned/favorite docs (paths) — kept in localStorage, shown atop the tree
function _pinned() { try { return JSON.parse(localStorage.getItem('docs-pinned') || '[]'); } catch { return []; } }
function _setPinned(a) { localStorage.setItem('docs-pinned', JSON.stringify(a)); }
function togglePin(path) {
  const a = _pinned(); const i = a.indexOf(path);
  if (i >= 0) a.splice(i, 1); else a.unshift(path);
  _setPinned(a); loadTree();
}
const _SORTS = [['name', 'a–z'], ['za', 'z–a'], ['recent', 'edited ↓'], ['oldest', 'edited ↑'], ['type', 'type']];
function cycleSort() {
  const i = _SORTS.findIndex(s => s[0] === _sortMode);
  _sortMode = _SORTS[(i + 1) % _SORTS.length][0];
  localStorage.setItem('docs-sort', _sortMode); _syncSortBtn(); loadTree();
}
function _syncSortBtn() { const b = $('wiki-sort-btn'); if (b) b.textContent = (_SORTS.find(s => s[0] === _sortMode) || _SORTS[0])[1]; }

// collapsed folders (paths) — persisted, so folders fold/unfold like a real tree
function _collapsed() { try { return new Set(JSON.parse(localStorage.getItem('docs-collapsed') || '[]')); } catch { return new Set(); } }
function _setCollapsed(s) { localStorage.setItem('docs-collapsed', JSON.stringify([...s])); }
function toggleCollapse(path) { const c = _collapsed(); c.has(path) ? c.delete(path) : c.add(path); _setCollapsed(c); loadTree(); }

// drag-to-move: which row is being dragged
let _dragPath = null;
function _canDrop(src, destDir) {
  if (!src || src === destDir) return false;
  if (destDir === src || destDir.startsWith(src + '/')) return false;   // a folder into its own subtree
  const parent = src.includes('/') ? src.slice(0, src.lastIndexOf('/')) : '';
  return parent !== destDir;                                            // already sitting there
}
async function moveInto(src, destDir) {
  const name = src.split('/').pop();
  const newPath = destDir ? destDir + '/' + name : name;
  try {
    const r = await fetch('/api/vault-md/rename', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: src, new_path: newPath }) });
    if (!r.ok) throw new Error();
    const res = await r.json();
    if (_cur === src) { _cur = res.path || newPath; const cl = $('wiki-current'); if (cl) cl.textContent = _cur.replace(/\.md$/, ''); }
    if (destDir) { const c = _collapsed(); c.delete(destDir); _setCollapsed(c); }   // reveal where it landed
    await loadTree();
    toast(destDir ? `moved into ${destDir.split('/').pop()}` : 'moved to top level', 'success');
  } catch { toast('move failed', 'error'); }
}

// ── view mode ────────────────────────────────────────────────────────────────
const _DOCS_MODES = ['live', 'source', 'preview'];
let _docsMode = localStorage.getItem('docs-view-mode');
if (!_DOCS_MODES.includes(_docsMode)) _docsMode = _docsMode === 'split' ? 'live' : (_docsMode === 'edit' ? 'source' : 'live');

async function applyDocsMode() {
  const v = $('wiki-view');
  if (!v) return;
  v.classList.toggle('docs-source', _docsMode === 'source');
  v.classList.toggle('docs-preview', _docsMode === 'preview');
  const btn = $('wiki-mode-toggle');
  if (btn) btn.textContent = _docsMode;
  if (_docsMode === 'live') { await ensureCM(); cmSet(getEditor()); _cm?.view.requestMeasure(); }
  else if (_docsMode === 'preview') renderPreview();
}
function cycleMode() {
  _docsMode = _DOCS_MODES[(_DOCS_MODES.indexOf(_docsMode) + 1) % _DOCS_MODES.length];
  localStorage.setItem('docs-view-mode', _docsMode);
  applyDocsMode().then(() => {
    if (_docsMode === 'live') _cm?.focus();
    else if (_docsMode === 'source') $('wiki-source')?.focus();
  });
}

// ── CodeMirror live surface (lazy-loaded) ────────────────────────────────────
// #wiki-source (textarea) is the canonical mirror that everything reads (save,
// preview, outline). CM syncs its value into the mirror on every change.
let _cm = null, _cmLoading = null, _applyingExternal = false;

function ensureCM() {
  const host = $('wiki-live');
  if (!host || _cm) return Promise.resolve();
  if (_cmLoading) return _cmLoading;
  _cmLoading = import('/static/vendor/cm6.bundle.js').then(mod => {
    _cm = mod.createDocEditor(host, {
      doc: getEditor(),
      onChange: (val) => {
        const ta = $('wiki-source'); if (ta) ta.value = val;
        updateStats();
        if (!_applyingExternal) queueSave();
      },
      wikiComplete: async (q) => {
        const res = await fetch(`/api/vault-md/search?q=${encodeURIComponent(q)}`).then(r => r.json()).catch(() => ({ results: [] }));
        return res.results || [];
      },
      onImageUpload: uploadImage,
    });
    window._cmEditor = _cm;   // debug handle (like the old _docEd)
  }).catch(e => {
    // graceful: fall back to the raw source textarea if CM can't load
    console.error('codemirror failed to load:', e);
    toast('rich editor failed to load — raw markdown mode', 'error');
    _docsMode = 'source';
    $('wiki-view')?.classList.add('docs-source');
    const btn = $('wiki-mode-toggle'); if (btn) btn.textContent = 'source';
  });
  return _cmLoading;
}
// push an external value into CM without triggering a save (open / ai-edit / reset)
function cmSet(md) {
  if (!_cm || _cm.getValue() === (md || '')) return;
  _applyingExternal = true;
  _cm.setValue(md || '');
  setTimeout(() => { _applyingExternal = false; }, 0);
}

function getEditor() { return $('wiki-source')?.value ?? ''; }
function setEditor(md) {
  md = md || '';
  const ta = $('wiki-source'); if (ta) ta.value = md;
  cmSet(md);
  updateStats();
  if (_docsMode === 'preview') renderPreview();
}

// upload a pasted/dropped image → _assets/, return its embed path for ![[ ]]
async function uploadImage(file) {
  const fd = new FormData();
  fd.append('file', file, file.name || 'image.png');
  const r = await fetch('/api/vault-md/asset', { method: 'POST', body: fd });
  if (!r.ok) { toast('image upload failed', 'error'); throw new Error('upload failed'); }
  const d = await r.json();
  toast('image added', 'success');
  return d.path;
}

// word count + reading time in the header (live)
function updateStats() {
  const el = $('wiki-stats'); if (!el) return;
  if (!_cur) { el.textContent = ''; return; }
  let t = getEditor().replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '');   // drop frontmatter
  t = t.replace(/```[\s\S]*?```/g, ' ').replace(/[#>*_`~\-\[\]()|]/g, ' ');
  const words = (t.match(/[^\s]+/g) || []).length;
  const mins = Math.max(1, Math.round(words / 200));
  el.textContent = words ? `${words} word${words !== 1 ? 's' : ''} · ${mins} min` : '';
}

// ── one-click formatting (live → CodeMirror, source → textarea) ──────────────
const _liveFmt = () => _docsMode === 'live' && _cm;
function wrapSel(pre, suf) { _liveFmt() ? _cm.wrap(pre, suf) : taWrap(pre, suf); }
function toggleLinePrefix(p) { _liveFmt() ? _cm.linePrefix(p) : taLinePrefix(p); }
function insertBlock(s) { _liveFmt() ? _cm.insertBlock(s) : taBlock(s); }
function insertLink() { wrapSel('[', '](url)'); }
function insertImage() { wrapSel('![', '](url)'); }
function insertWiki() { wrapSel('[[', ']]'); }

// textarea (source mode) editing helpers
function _taApply(ta, value, a, b) { ta.value = value; ta.setSelectionRange(a, b); ta.focus(); onSourceInput(); }
function taWrap(pre, suf) {
  const ta = $('wiki-source'); if (!ta) return;
  const { selectionStart: a, selectionEnd: b, value: t } = ta;
  if (a === b) { const ph = 'text'; _taApply(ta, t.slice(0, a) + pre + ph + suf + t.slice(b), a + pre.length, a + pre.length + ph.length); }
  else _taApply(ta, t.slice(0, a) + pre + t.slice(a, b) + suf + t.slice(b), a + pre.length, b + pre.length);
}
function taLinePrefix(prefix) {
  const ta = $('wiki-source'); if (!ta) return;
  const t = ta.value, a = ta.selectionStart;
  const ls = t.lastIndexOf('\n', a - 1) + 1;
  let le = t.indexOf('\n', a); if (le < 0) le = t.length;
  const line = t.slice(ls, le);
  const indent = (/^\s*/.exec(line) || [''])[0];
  const rest = line.slice(indent.length).replace(/^(#{1,6}\s+|[-*]\s+(?:\[[ xX]\]\s+)?|\d+\.\s+|>\s?)/, '');
  const newLine = indent + (line.slice(indent.length).startsWith(prefix) ? rest : prefix + rest);
  const caret = ls + newLine.length;
  _taApply(ta, t.slice(0, ls) + newLine + t.slice(le), caret, caret);
}
function taBlock(snippet) {
  const ta = $('wiki-source'); if (!ta) return;
  const t = ta.value, a = ta.selectionStart, b = ta.selectionEnd;
  const before = t.slice(0, a);
  const lead = (before && !before.endsWith('\n')) ? '\n' : '';
  let body = lead + snippet; let caret = body.indexOf('{}');
  if (caret >= 0) body = body.replace('{}', ''); else caret = body.length;
  _taApply(ta, before + body + t.slice(b), a + caret, a + caret);
}

// ── text color: {color:hex}text{/color} + swatch / custom picker popup ───────
const _DOCS_COLORS = [
  ['#f87171', 'red'], ['#fb923c', 'orange'], ['#fbbf24', 'amber'], ['#facc15', 'yellow'],
  ['#a3e635', 'lime'], ['#4ade80', 'green'], ['#34d399', 'emerald'], ['#22d3ee', 'cyan'],
  ['#60a5fa', 'blue'], ['#818cf8', 'indigo'], ['#a78bfa', 'purple'], ['#e879f9', 'fuchsia'],
  ['#f472b6', 'pink'], ['#e8e6e3', 'white'],
];
function _hsvToHex(h, s, v) {
  const c = v * s, x = c * (1 - Math.abs((h / 60) % 2 - 1)), m = v - c;
  let r, g, b;
  if (h < 60) [r, g, b] = [c, x, 0]; else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x]; else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c]; else [r, g, b] = [c, 0, x];
  const to = n => Math.round((n + m) * 255).toString(16).padStart(2, '0');
  return '#' + to(r) + to(g) + to(b);
}
function applyColor(hex) { if (hex) wrapSel(`{color:${hex}}`, '{/color}'); }
function _toggleColorPalette(btn) {
  document.getElementById('dt-color-pop')?.remove();
  const pop = document.createElement('div');
  pop.id = 'dt-color-pop'; pop.className = 'dt-color-pop';
  pop.innerHTML = _DOCS_COLORS.map(([hex, name]) => `<button class="dt-swatch" style="background:${hex}" title="${name}" data-hex="${hex}"></button>`).join('')
    + `<div class="dt-picker"><div class="dt-sv"><div class="dt-sv-dot"></div></div><div class="dt-hue"><div class="dt-hue-handle"></div></div></div>`
    + `<input class="dt-hex" type="text" placeholder="or type #hex / css color" spellcheck="false">`;
  document.body.appendChild(pop);
  const r = btn.getBoundingClientRect();
  pop.style.left = Math.min(r.left, window.innerWidth - 234) + 'px';
  pop.style.top = Math.min(r.bottom + 4, window.innerHeight - pop.offsetHeight - 8) + 'px';
  pop.querySelectorAll('.dt-swatch').forEach(sw =>
    sw.addEventListener('mousedown', e => { e.preventDefault(); applyColor(sw.dataset.hex); pop.remove(); }));
  _initColorPicker(pop);
  const hex = pop.querySelector('.dt-hex');
  hex.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); const v = hex.value.trim(); if (/^[#\w(),.%\s-]+$/.test(v)) { applyColor(v); pop.remove(); } }
    else if (e.key === 'Escape') pop.remove();
  });
  setTimeout(() => document.addEventListener('mousedown', function h(ev) {
    if (!pop.contains(ev.target) && ev.target !== btn) { pop.remove(); document.removeEventListener('mousedown', h); }
  }), 0);
}
function _initColorPicker(pop) {
  const sv = pop.querySelector('.dt-sv'), hue = pop.querySelector('.dt-hue');
  const dot = sv.querySelector('.dt-sv-dot'), handle = hue.querySelector('.dt-hue-handle');
  let h = 250, s = 0.6, v = 0.95;
  const render = (commit) => {
    sv.style.background = `linear-gradient(to top, #000, rgba(0,0,0,0)), linear-gradient(to right, #fff, hsl(${h} 100% 50%))`;
    dot.style.left = (s * 100) + '%'; dot.style.top = ((1 - v) * 100) + '%';
    handle.style.left = (h / 360 * 100) + '%';
    const hex = _hsvToHex(h, s, v); dot.style.background = hex;
    if (commit) { applyColor(hex); const hx = pop.querySelector('.dt-hex'); if (hx) hx.value = hex; }
  };
  const track = (el, onMove) => {
    const pt = e => { const r = el.getBoundingClientRect(); onMove(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)), Math.max(0, Math.min(1, (e.clientY - r.top) / r.height))); render(true); };
    el.addEventListener('pointerdown', e => {
      e.preventDefault(); try { el.setPointerCapture(e.pointerId); } catch {}
      pt(e);
      const mv = ev => pt(ev);
      const up = () => { el.removeEventListener('pointermove', mv); el.removeEventListener('pointerup', up); el.removeEventListener('pointercancel', up); };
      el.addEventListener('pointermove', mv); el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
    });
  };
  track(sv, (x, y) => { s = x; v = 1 - y; });
  track(hue, (x) => { h = x * 360; });
  render(false);
}

const _FMT = {
  bold: () => wrapSel('**', '**'), italic: () => wrapSel('*', '*'), strike: () => wrapSel('~~', '~~'),
  highlight: () => wrapSel('==', '=='), code: () => wrapSel('`', '`'),
  h1: () => toggleLinePrefix('# '), h2: () => toggleLinePrefix('## '), h3: () => toggleLinePrefix('### '),
  bullet: () => toggleLinePrefix('- '), olist: () => toggleLinePrefix('1. '), check: () => toggleLinePrefix('- [ ] '),
  quote: () => toggleLinePrefix('> '),
  link: () => insertLink(), image: () => insertImage(), wiki: () => insertWiki(),
  hr: () => insertBlock('---'),
  table: () => insertBlock('| {}col 1 | col 2 |\n| --- | --- |\n| a | b |'),
  codeblock: () => insertBlock('```\n{}\n```'),
  callout: () => insertBlock('> [!note] {}title\n> body'),
  math: () => insertBlock('$$\n{}\n$$'),
  mermaid: () => insertBlock('```mermaid\ngraph TD;\n  {}A --> B\n```'),
};
let _toolbarInited = false;
function initDocsToolbar() {
  const bar = $('docs-toolbar');
  if (!bar || _toolbarInited) return;
  _toolbarInited = true;
  bar.querySelectorAll('.dt-btn[data-fmt]').forEach(b =>
    b.addEventListener('mousedown', e => { e.preventDefault(); _FMT[b.dataset.fmt]?.(); }));
  $('dt-color-btn')?.addEventListener('mousedown', e => { e.preventDefault(); _toggleColorPalette(e.currentTarget); });
}

export function initVault() {
  if (_inited) { loadTree(); return; }
  _inited = true;
  if (localStorage.getItem('docs-tree-hidden') !== '0') $('wiki-view')?.classList.add('tree-hidden');
  $('wiki-tree-toggle')?.addEventListener('click', () => {
    const hidden = $('wiki-view')?.classList.toggle('tree-hidden');
    localStorage.setItem('docs-tree-hidden', hidden ? '1' : '0');
    if (_docsMode === 'live') _cm?.view.requestMeasure();
  });
  $('wiki-mode-toggle')?.addEventListener('click', cycleMode);
  $('wiki-ai-toggle')?.addEventListener('click', () => {
    const on = $('wiki-view').classList.toggle('ai-open');
    $('wiki-ai-toggle').classList.toggle('active', on);
    if (on) $('wiki-ai-input')?.focus();
  });
  $('wiki-new-btn')?.addEventListener('click', newNote);
  $('wiki-delete-btn')?.addEventListener('click', deleteCurrent);
  $('wiki-export-btn')?.addEventListener('click', e => openExportMenu(e.currentTarget));
  $('wiki-folder-btn')?.addEventListener('click', newFolder);
  $('wiki-tmpl-btn')?.addEventListener('click', e => openTemplateMenu(e.currentTarget));
  $('wiki-import-btn')?.addEventListener('click', e => openImportMenu(e.currentTarget));
  $('wiki-import-input')?.addEventListener('change', importDoc);
  $('wiki-sort-btn')?.addEventListener('click', cycleSort);
  // drop a nested file/folder onto empty tree space → move it back to the top level
  const treeEl = $('wiki-tree');
  if (treeEl) {
    treeEl.addEventListener('dragover', e => { if (_canDrop(_dragPath, '') && !e.target.closest('.wiki-dir')) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; } });
    treeEl.addEventListener('drop', e => { if (e.target.closest('.wiki-dir') || !_canDrop(_dragPath, '')) return; e.preventDefault(); moveInto(_dragPath, ''); });
  }
  $('wiki-today-btn')?.addEventListener('click', openDaily);
  $('wiki-week-btn')?.addEventListener('click', () => openPeriodic('weekly'));
  $('wiki-month-btn')?.addEventListener('click', () => openPeriodic('monthly'));
  $('wiki-outline-btn')?.addEventListener('click', toggleOutline);
  $('wiki-props-btn')?.addEventListener('click', toggleProps);
  $('wiki-query-btn')?.addEventListener('click', toggleQuery);
  $('wiki-todos-btn')?.addEventListener('click', extractTodos);
  $('wiki-taskroll-btn')?.addEventListener('click', toggleTaskRoll);
  $('wiki-history-btn')?.addEventListener('click', toggleHistory);
  _syncSortBtn();
  // docs-scoped shortcuts: Ctrl/Cmd+O quick switcher, Ctrl/Cmd+F find (live mode)
  document.addEventListener('keydown', e => {
    if (!_docsVisible()) return;
    const mod = e.ctrlKey || e.metaKey;
    if (!mod || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === 'o' && !e.shiftKey) { e.preventDefault(); openQuickSwitcher(); }
    else if (k === 'f' && !e.shiftKey && _docsMode === 'live' && _cm) { e.preventDefault(); _cm.openSearch(); }
  });
  $('wiki-graph-btn')?.addEventListener('click', openGraph);
  $('wiki-graph-close')?.addEventListener('click', () => { $('wiki-graph').style.display = 'none'; });
  $('wiki-help-btn')?.addEventListener('click', () => {
    const h = $('wiki-help');
    if (h) h.style.display = h.style.display === 'none' ? 'block' : 'none';
  });
  $('wiki-help-close')?.addEventListener('click', () => { $('wiki-help').style.display = 'none'; });
  let _searchT = 0;
  $('wiki-search')?.addEventListener('input', e => {
    clearTimeout(_searchT);
    _searchT = setTimeout(() => doSearch(e.target.value.trim()), 160);
  });
  $('wiki-preview')?.addEventListener('click', e => {
    const tag = e.target.closest('.md-tag');
    if (tag) { filterByTag(tag.dataset.tag); return; }
    const a = e.target.closest('.wikilink');
    if (a) { e.preventDefault(); openByName(a.dataset.note); }
  });
  $('wiki-empty-new')?.addEventListener('click', newNote);
  $('wiki-empty-today')?.addEventListener('click', openDaily);
  $('wiki-empty-guide')?.addEventListener('click', () => { const h = $('wiki-help'); if (h) h.style.display = 'block'; });
  $('wiki-ai-send')?.addEventListener('click', aiEdit);
  $('wiki-ai-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') aiEdit(); });

  const ta = $('wiki-source');
  if (ta) {
    ta.addEventListener('input', onSourceInput);
    ta.addEventListener('keydown', onSourceKeydown);
    ta.addEventListener('blur', () => setTimeout(hideAc, 120));
    ta.addEventListener('click', () => hideAc());
  }
  initDocsToolbar();
  applyDocsMode();
  loadTree();
}

// ── source (raw textarea) mode ───────────────────────────────────────────────
function onSourceInput() {
  if (!_cur) return;
  updateStats();
  queueSave();
  autocomplete();
}
function onSourceKeydown(e) {
  if ($('wiki-autocomplete')?.style.display === 'block' && _acItems.length) {
    acKeydown(e);
    if (e.defaultPrevented) return;
  }
  const mod = e.ctrlKey || e.metaKey;
  if (mod && !e.altKey) {
    const k = e.key.toLowerCase(); let hit = true;
    if      (k === 'b' && !e.shiftKey) wrapSel('**', '**');
    else if (k === 'i' && !e.shiftKey) wrapSel('*', '*');
    else if (k === 'e' && !e.shiftKey) wrapSel('`', '`');
    else if (k === 'k' && !e.shiftKey) insertLink();
    else if (k === 'x' && e.shiftKey)  wrapSel('~~', '~~');
    else if (k === 'h' && e.shiftKey)  wrapSel('==', '==');
    else hit = false;
    if (hit) { e.preventDefault(); return; }
  }
  if (e.key === 'Tab') {
    e.preventDefault();
    const ta = $('wiki-source'); const { selectionStart: a, selectionEnd: b, value: t } = ta;
    ta.value = t.slice(0, a) + '  ' + t.slice(b); ta.setSelectionRange(a + 2, a + 2); onSourceInput();
  }
}

// ── ai edit (streams the rewrite into the editor) ────────────────────────────
function _setEditorContent(md) { setEditor(md || ''); }

async function aiEdit() {
  if (!_cur) { toast('open a doc first', 'error'); return; }
  const inp = $('wiki-ai-input');
  const instruction = inp.value.trim();
  if (!instruction) return;
  inp.value = '';
  await flushSave();
  const status = $('wiki-save-status');
  const t0 = Date.now();
  let phase = 'thinking';
  status.textContent = 'ai thinking…';
  const tick = setInterval(() => { status.textContent = `ai ${phase}… ${Math.round((Date.now() - t0) / 1000)}s`; }, 500);

  let acc = '', paintT = 0, lastPaint = 0;
  const paint = () => { paintT = 0; lastPaint = Date.now(); _setEditorContent(acc); };
  const schedule = () => {
    if (paintT) return;
    const since = Date.now() - lastPaint;
    if (since >= 150) paint(); else paintT = setTimeout(paint, 150 - since);
  };
  const stop = () => { clearInterval(tick); if (paintT) { clearTimeout(paintT); paintT = 0; } };

  try {
    const r = await fetch('/api/vault-md/ai-edit', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ path: _cur, instruction }),
    });
    if (!r.ok) { stop(); toast('ai edit failed', 'error'); status.textContent = ''; return; }
    const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = '';
    let err = '';
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n'); buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        const raw = line.slice(5).trim();
        if (raw === '[DONE]') continue;
        let c; try { c = JSON.parse(raw); } catch { continue; }
        if (c.error) err = c.error;
        if (c.delta) { phase = 'writing'; acc += c.delta; schedule(); }
      }
    }
    stop();
    if (!acc.trim()) { toast(err ? err.slice(0, 140) : 'ai returned nothing — doc unchanged', 'error'); status.textContent = ''; return; }
    _setEditorContent(acc);
    status.textContent = 'saved';
    loadBacklinks();
  } catch {
    stop();
    toast('ai edit failed', 'error'); status.textContent = '';
    if (acc) openFile(_cur);
  }
}

let _activeTag = null;

function _flattenFiles(items, out = []) {
  for (const it of items || []) {
    if (it.type === 'dir') _flattenFiles(it.children, out);
    else out.push(it);
  }
  return out;
}
function renderRecent(items) {
  const el = $('wiki-empty-recent');
  if (!el) return;
  const files = _flattenFiles(items).slice(0, 8);
  if (!files.length) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="we-recent-label">your docs</div><div class="we-recent-list">`
    + files.map(f => `<button class="we-recent-item" data-path="${esc(f.path)}">${esc(f.name)}</button>`).join('')
    + `</div>`;
  el.querySelectorAll('.we-recent-item').forEach(b => b.addEventListener('click', () => openFile(b.dataset.path)));
}

function _fileRow(f) {
  const active = f.path === _cur ? ' active' : '';
  return `<div class="wiki-file${active}" data-path="${esc(f.path)}"><span class="wiki-row-label">${esc(f.name)}</span>${_rowActs('file', f.path)}</div>`;
}

async function loadTree() {
  _activeTag = null;
  _syncEmpty();
  const search = $('wiki-search');
  if (search) search.value = '';
  loadTags();
  const el = $('wiki-tree');
  if (!el) return;
  try {
    const t = await fetch('/api/vault-md/tree').then(r => r.json());
    const files = _flattenFiles(t.items);
    let html = '';
    const pins = _pinned().map(p => files.find(f => f.path === p)).filter(Boolean);
    if (pins.length) html += `<div class="wiki-pinned"><div class="wiki-pinned-label">pinned</div>${pins.map(_fileRow).join('')}</div>`;
    const _ext = f => (f.name || '').split('.').slice(1).pop() || '';
    const flat = {
      za:     [...files].sort((a, b) => (b.name || '').localeCompare(a.name || '')),
      recent: [...files].sort((a, b) => (b.mtime || 0) - (a.mtime || 0)),
      oldest: [...files].sort((a, b) => (a.mtime || 0) - (b.mtime || 0)),
      type:   [...files].sort((a, b) => _ext(a).localeCompare(_ext(b)) || (a.name || '').localeCompare(b.name || '')),
    };
    if (flat[_sortMode]) {
      html += flat[_sortMode].map(_fileRow).join('');
    } else {
      html += t.items.length ? renderItems(t.items, 0) : '';   // 'name' = hierarchical a–z
    }
    el.innerHTML = html || '<div class="wiki-empty">docs empty - create one</div>';
    el.querySelectorAll('.wiki-file').forEach(f => _wireRow(f, 'file'));
    el.querySelectorAll('.wiki-dir').forEach(d => _wireRow(d, 'dir'));
    renderRecent(t.items);
  } catch { el.innerHTML = '<div class="wiki-empty">failed to load</div>'; }
}

async function loadTags() {
  const el = $('wiki-tags');
  if (!el) return;
  try {
    const d = await fetch('/api/vault-md/tags').then(r => r.json());
    el.innerHTML = (d.tags || []).map(t =>
      `<span class="wiki-tag${t.tag === _activeTag ? ' active' : ''}" data-tag="${esc(t.tag)}">#${esc(t.tag)} <em>${t.count}</em></span>`).join('');
    el.querySelectorAll('.wiki-tag').forEach(t => t.addEventListener('click', () => filterByTag(t.dataset.tag)));
  } catch {}
}

async function filterByTag(tag) {
  if (_activeTag === tag) { loadTree(); return; }
  _activeTag = tag;
  loadTags();
  const el = $('wiki-tree');
  try {
    const d = await fetch(`/api/vault-md/tag?tag=${encodeURIComponent(tag)}`).then(r => r.json());
    el.innerHTML = `<div class="wiki-filter-note">#${esc(tag)} · ${d.notes.length}</div>`
      + d.notes.map(n => `<div class="wiki-file" data-path="${esc(n.path)}">${esc(n.name)}</div>`).join('');
    el.querySelectorAll('.wiki-file').forEach(f => f.addEventListener('click', () => openFile(f.dataset.path)));
  } catch {}
}

async function doSearch(q) {
  if (!q) { loadTree(); return; }
  const el = $('wiki-tree');
  try {
    const d = await fetch(`/api/vault-md/grep?q=${encodeURIComponent(q)}`).then(r => r.json());
    if (!d.results.length) { el.innerHTML = '<div class="wiki-empty">no matches</div>'; return; }
    el.innerHTML = d.results.map(r =>
      `<div class="wiki-file wiki-search-hit" data-path="${esc(r.path)}"><div>${esc(r.name)}</div>${r.context ? `<span>${esc(r.context)}</span>` : ''}</div>`).join('');
    el.querySelectorAll('.wiki-file').forEach(f => f.addEventListener('click', () => openFile(f.dataset.path)));
  } catch { el.innerHTML = '<div class="wiki-empty">search failed</div>'; }
}

async function newFolder() {
  const name = await dlgPrompt('folder name:');
  if (!name?.trim()) return;
  await fetch('/api/vault-md/folder', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: name.trim() }) });
  loadTree();
}

// ── graph view ────────────────────────────────────────────────────────────
async function openGraph() {
  const box = $('wiki-graph');
  box.style.display = 'flex';
  try { renderGraph(await fetch('/api/vault-md/graph').then(r => r.json())); }
  catch { toast('graph failed', 'error'); }
}
function renderGraph(data) {
  const svg = $('wiki-graph-svg');
  const W = svg.clientWidth || 700, H = svg.clientHeight || 520;
  const nodes = data.nodes.map(n => ({ ...n, x: W / 2 + (Math.random() - 0.5) * 200, y: H / 2 + (Math.random() - 0.5) * 200, vx: 0, vy: 0 }));
  const idx = {}; nodes.forEach(n => idx[n.id] = n);
  const edges = data.edges.filter(e => idx[e.source] && idx[e.target]);
  for (let it = 0; it < 140; it++) {
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j]; let dx = a.x - b.x, dy = a.y - b.y; const d = Math.hypot(dx, dy) || 1;
      const f = 2600 / (d * d); dx /= d; dy /= d; a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
    }
    for (const e of edges) {
      const a = idx[e.source], b = idx[e.target]; let dx = b.x - a.x, dy = b.y - a.y; const d = Math.hypot(dx, dy) || 1;
      const f = (d - 90) * 0.012; dx /= d; dy /= d; a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
    }
    for (const n of nodes) {
      n.vx += (W / 2 - n.x) * 0.003; n.vy += (H / 2 - n.y) * 0.003;
      n.x += n.vx * 0.82; n.y += n.vy * 0.82; n.vx *= 0.82; n.vy *= 0.82;
      n.x = Math.max(24, Math.min(W - 24, n.x)); n.y = Math.max(24, Math.min(H - 24, n.y));
    }
  }
  let html = '';
  for (const e of edges) html += `<line x1="${idx[e.source].x.toFixed(1)}" y1="${idx[e.source].y.toFixed(1)}" x2="${idx[e.target].x.toFixed(1)}" y2="${idx[e.target].y.toFixed(1)}" class="wg-edge"/>`;
  for (const n of nodes) {
    const r = 4 + Math.min(11, n.degree * 1.6);
    html += `<g class="wg-node" data-path="${esc(n.path)}"><circle cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="${r}"/><text x="${n.x.toFixed(1)}" y="${(n.y - r - 4).toFixed(1)}">${esc(n.id)}</text></g>`;
  }
  svg.innerHTML = html;
  svg.querySelectorAll('.wg-node').forEach(g => g.addEventListener('click', () => { $('wiki-graph').style.display = 'none'; openFile(g.dataset.path); }));
}

function _rowActs(kind, path) {
  const pinned = _pinned().includes(path);
  const pin = kind === 'file'
    ? `<button class="wiki-row-act wiki-pin${pinned ? ' on' : ''}" data-act="pin" title="${pinned ? 'unpin' : 'pin'}">${pinned ? '★' : '☆'}</button>` : '';
  return `<span class="wiki-row-acts">${pin}<button class="wiki-row-act" data-act="rename" title="rename">✎</button><button class="wiki-row-act" data-act="delete" title="delete">✕</button></span>`;
}
function renderItems(items, depth) {
  const collapsed = _collapsed();
  return items.map(it => {
    const pad = `style="padding-left:${0.4 + depth * 0.7}rem"`;
    if (it.type === 'dir') {
      const folded = collapsed.has(it.path);
      const n = (it.children || []).length;
      const row = `<div class="wiki-dir${folded ? ' folded' : ''}" data-path="${esc(it.path)}" ${pad}><span class="wiki-row-label"><span class="wiki-dir-arrow">${folded ? '▸' : '▾'}</span>${esc(it.name)}${n ? ` <em class="wiki-dir-count">${n}</em>` : ''}</span>${_rowActs('dir', it.path)}</div>`;
      return row + (folded ? '' : renderItems(it.children || [], depth + 1));
    }
    const active = it.path === _cur ? ' active' : '';
    return `<div class="wiki-file${active}" data-path="${esc(it.path)}" ${pad}><span class="wiki-row-label">${esc(it.name)}</span>${_rowActs('file', it.path)}</div>`;
  }).join('');
}
function _wireRow(row, kind) {
  const rowPath = row.dataset.path;
  row.querySelector('.wiki-row-label')?.addEventListener('click', () => {
    if (kind === 'file') openFile(rowPath);
    else toggleCollapse(rowPath);
  });
  // drag a file/folder to move it; folders are drop targets
  row.setAttribute('draggable', 'true');
  row.addEventListener('dragstart', e => { e.stopPropagation(); _dragPath = rowPath; e.dataTransfer.effectAllowed = 'move'; try { e.dataTransfer.setData('text/plain', rowPath); } catch {} row.classList.add('dragging'); });
  row.addEventListener('dragend', () => { row.classList.remove('dragging'); _dragPath = null; document.querySelectorAll('.wiki-drop-into').forEach(x => x.classList.remove('wiki-drop-into')); });
  if (kind === 'dir') {
    row.addEventListener('dragover', e => { if (_canDrop(_dragPath, rowPath)) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; row.classList.add('wiki-drop-into'); } });
    row.addEventListener('dragleave', () => row.classList.remove('wiki-drop-into'));
    row.addEventListener('drop', e => { row.classList.remove('wiki-drop-into'); if (!_canDrop(_dragPath, rowPath)) return; e.preventDefault(); e.stopPropagation(); moveInto(_dragPath, rowPath); });
  }
  row.querySelectorAll('.wiki-row-act').forEach(b => b.addEventListener('click', async e => {
    e.stopPropagation();
    const path = row.dataset.path;
    if (b.dataset.act === 'pin') { togglePin(path); return; }
    if (b.dataset.act === 'rename') {
      const cur = path.split('/').pop().replace(/\.md$/, '');
      const name = await dlgPrompt(`rename ${kind}:`, cur);
      if (!name?.trim() || name.trim() === cur) return;
      const parent = path.includes('/') ? path.slice(0, path.lastIndexOf('/') + 1) : '';
      const rr = await fetch('/api/vault-md/rename', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path, new_path: parent + name.trim() }) }).then(r => r.json()).catch(() => ({}));
      if (rr.links_rewritten) toast(`updated ${rr.links_rewritten} note${rr.links_rewritten > 1 ? 's' : ''} linking here`, 'success');
      if (_cur === path) _resetEditor();
      loadTree();
    } else {
      if (!await dlgConfirm(`delete ${kind} "${path}"?`)) return;
      await fetch(`/api/vault-md/file?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
      if (_cur && (_cur === path || _cur.startsWith(path + '/'))) _resetEditor();
      loadTree();
    }
  }));
}

function _resetEditor() {
  _cur = null; _syncEmpty();
  setEditor('');
  $('wiki-preview').innerHTML = '';
  $('wiki-backlinks').innerHTML = '';
  const cl = $('wiki-current'); if (cl) cl.textContent = 'no doc open';
}

export function openNote(path) {
  if (!_inited) initVault();
  return openFile(path);
}

async function openFile(path) {
  await flushSave();
  try {
    const d = await fetch(`/api/vault-md/file?path=${encodeURIComponent(path)}`).then(r => r.json());
    _cur = d.path || path;
    _syncEmpty();
    setEditor(d.content || '');
    const currentLabel = $('wiki-current');
    if (currentLabel) currentLabel.textContent = _cur.replace(/\.md$/, '');
    loadBacklinks();
    document.querySelectorAll('.wiki-file').forEach(f => f.classList.toggle('active', f.dataset.path === _cur));
    if (_docsMode === 'live') { _cm?.view.requestMeasure(); _cm?.focus(); }
    else if (_docsMode === 'source') $('wiki-source')?.focus();
  } catch { toast('failed to open doc', 'error'); }
}

async function openByName(name) {
  const res = await fetch(`/api/vault-md/search?q=${encodeURIComponent(name)}`).then(r => r.json()).catch(() => ({ results: [] }));
  const hit = (res.results || []).find(r => r.name.toLowerCase() === name.toLowerCase());
  if (hit) return openFile(hit.path);
  await fetch('/api/vault-md/file', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: name }) });
  await loadTree();
  openFile(name.endsWith('.md') ? name : name + '.md');
}

const _embedCache = {};
function renderPreview() {
  let src = getEditor();
  let fmHtml = '';
  const fm = src.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (fm) { fmHtml = renderFrontmatter(fm[1]); src = src.slice(fm[0].length); }
  let html = mdToHtml(src);
  html = html.replace(/!\[\[([^\]|#]+?)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]/g, (_, name, alias) => embedHtml(name.trim(), alias));
  html = html.replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]/g, (_, name, alias) => `<a class="wikilink" data-note="${esc(name.trim())}">${esc((alias || name).trim())}</a>`);
  html = html.replace(/(^|[\s(>])#([A-Za-z0-9][A-Za-z0-9_/\-]*)/g, (_, pre, tag) => `${pre}<span class="md-tag" data-tag="${esc(tag)}">#${esc(tag)}</span>`);
  $('wiki-preview').innerHTML = fmHtml + html;
  enhanceMarkdown($('wiki-preview'));
  fillEmbeds();
  if ($('wiki-outline') && $('wiki-outline').style.display !== 'none') updateOutline();
}
function renderFrontmatter(raw) {
  const rows = [];
  for (const line of raw.split('\n')) { const m = line.match(/^([A-Za-z0-9_][\w \-]*):\s*(.*)$/); if (m) rows.push([m[1].trim(), m[2].trim()]); }
  if (!rows.length) return '';
  return `<div class="md-frontmatter">` + rows.map(([k, v]) => `<div class="md-fm-row"><span class="md-fm-key">${esc(k)}</span><span class="md-fm-val">${esc(v || '—')}</span></div>`).join('') + `</div>`;
}
const _IMG_RE = /\.(png|jpe?g|gif|webp|svg|bmp|ico)$/i;
function embedHtml(name, alias) {
  if (_IMG_RE.test(name)) return `<img class="md-embed-img" src="/api/vault-md/raw?path=${encodeURIComponent(name)}" alt="${esc(alias || name)}">`;
  const cached = _embedCache[name.toLowerCase()];
  const body = cached != null ? cached : '<span class="md-embed-loading">…</span>';
  return `<div class="md-embed" data-embed="${esc(name)}"><div class="md-embed-head wikilink" data-note="${esc(name)}">${esc(name)}</div><div class="md-embed-body">${body}</div></div>`;
}
function fillEmbeds() {
  $('wiki-preview').querySelectorAll('.md-embed[data-embed]').forEach(async el => {
    const name = el.dataset.embed, key = name.toLowerCase();
    const body = el.querySelector('.md-embed-body');
    if (_embedCache[key] != null) { body.innerHTML = _embedCache[key]; return; }
    let out;
    try {
      const res = await fetch(`/api/vault-md/search?q=${encodeURIComponent(name)}`).then(r => r.json());
      const hit = (res.results || []).find(r => r.name.toLowerCase() === key);
      if (!hit) out = '<span class="md-embed-loading">doc not found</span>';
      else { const d = await fetch(`/api/vault-md/file?path=${encodeURIComponent(hit.path)}`).then(r => r.json()); out = mdToHtml((d.content || '').replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '')); }
    } catch { out = '<span class="md-embed-loading">failed to load</span>'; }
    _embedCache[key] = out;
    if (body) body.innerHTML = out;
  });
}

async function extractTodos() {
  if (!_cur) { toast('open a doc first', 'error'); return; }
  await flushSave();
  const btn = $('wiki-todos-btn');
  btn.disabled = true; btn.textContent = 'extracting…';
  try {
    const r = await fetch('/api/vault-md/extract-todos', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: _cur }) });
    const d = await r.json();
    if (!r.ok) toast(d.detail || 'extraction failed', 'error');
    else if (!d.created) toast('no action items found in this doc', '');
    else toast(`${d.created} task${d.created !== 1 ? 's' : ''} created — check the tasks app`, 'success');
  } catch { toast('extraction failed', 'error'); }
  btn.disabled = false; btn.textContent = 'todos';
}

function toggleHistory() {
  const p = $('wiki-history'); if (!p) return;
  const show = p.style.display === 'none';
  p.style.display = show ? 'block' : 'none';
  $('wiki-history-btn')?.classList.toggle('active', show);
  if (show) loadHistory();
}
function _revAgo(iso) {
  const s = (Date.now() - new Date(iso + 'Z').getTime()) / 1000;
  if (s < 90) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
async function loadHistory() {
  const panel = $('wiki-history'); if (!panel) return;
  if (!_cur) { panel.innerHTML = '<div style="font-size:0.72rem;color:var(--muted)">open a doc first</div>'; return; }
  panel.innerHTML = '<div style="font-size:0.72rem;color:var(--muted)">loading…</div>';
  let revs;
  try { revs = await fetch(`/api/vault-md/revisions?path=${encodeURIComponent(_cur)}`).then(r => r.json()); }
  catch { panel.innerHTML = '<div style="font-size:0.72rem;color:var(--error)">failed to load history</div>'; return; }
  if (!revs.length) { panel.innerHTML = '<div style="font-size:0.72rem;color:var(--muted)">no earlier versions yet — snapshots are taken as you edit</div>'; return; }
  panel.innerHTML = revs.map(r => `
    <div class="wiki-rev" data-rev="${r.id}">
      <div style="display:flex;align-items:center;gap:0.5rem;padding:0.25rem 0;font-size:0.72rem">
        <span>${_revAgo(r.created_at)}</span><span style="color:var(--muted)">${(r.size / 1000).toFixed(1)}k</span><span style="flex:1"></span>
        <button class="btn" data-rev-diff="${r.id}" style="font-size:0.66rem">diff</button>
        <button class="btn" data-rev-restore="${r.id}" style="font-size:0.66rem">restore</button>
      </div>
      <div class="wiki-rev-diff" style="display:none"></div>
    </div>`).join('');
  panel.querySelectorAll('[data-rev-diff]').forEach(b => b.addEventListener('click', async () => {
    const box = b.closest('.wiki-rev').querySelector('.wiki-rev-diff');
    if (box.style.display !== 'none') { box.style.display = 'none'; return; }   // toggle off
    box.style.display = 'block'; box.textContent = 'loading…';
    try {
      const d = await fetch(`/api/vault-md/diff?path=${encodeURIComponent(_cur)}&a=${b.dataset.revDiff}`).then(r => r.json());
      box.innerHTML = _renderDiff(d.diff);
    } catch { box.innerHTML = '<div style="font-size:0.7rem;color:var(--error)">diff failed</div>'; }
  }));
  panel.querySelectorAll('[data-rev-restore]').forEach(b => b.addEventListener('click', async () => {
    if (!await dlgConfirm('restore this version? the current state is kept as a revision.')) return;
    try {
      const r = await fetch(`/api/vault-md/revisions/${b.dataset.revRestore}/restore`, { method: 'POST' });
      if (!r.ok) throw new Error();
      await openFile(_cur); toast('version restored', 'success'); loadHistory();
    } catch { toast('restore failed', 'error'); }
  }));
}
// color a unified diff (vs the current file). add=green, remove=red, hunk=accent
function _renderDiff(txt) {
  if (!txt || !txt.trim()) return '<div style="font-size:0.7rem;color:var(--muted)">no changes vs current version</div>';
  const body = txt.split('\n').map(l => {
    let c = 'var(--muted)';
    if (l.startsWith('+') && !l.startsWith('+++')) c = 'var(--green)';
    else if (l.startsWith('-') && !l.startsWith('---')) c = 'var(--error)';
    else if (l.startsWith('@@')) c = 'var(--accent)';
    return `<span style="color:${c}">${esc(l)}</span>`;
  }).join('\n');
  return `<pre style="margin:0.3rem 0 0.5rem;padding:0.4rem;background:var(--panel);border:1px solid var(--faint);border-radius:3px;font-size:0.66rem;white-space:pre-wrap;overflow-x:auto">${body}</pre>`;
}

function toggleOutline() {
  const p = $('wiki-outline'); if (!p) return;
  const show = p.style.display === 'none';
  p.style.display = show ? 'block' : 'none';
  $('wiki-outline-btn')?.classList.toggle('active', show);
  if (show) updateOutline();
}
function updateOutline() {
  const panel = $('wiki-outline'); if (!panel) return;
  const lines = getEditor().split('\n');
  const heads = []; let inFm = false;
  lines.forEach((line, i) => {
    if (i === 0 && line.trim() === '---') { inFm = true; return; }
    if (inFm) { if (line.trim() === '---') inFm = false; return; }
    const m = line.match(/^(#{1,6})\s+(.+)$/);
    if (m) heads.push({ level: m[1].length, text: m[2].trim(), line: i });
  });
  if (!heads.length) { panel.innerHTML = '<div class="wiki-outline-empty">no headings</div>'; return; }
  panel.innerHTML = `<div class="wiki-outline-head">outline</div>` + heads.map(h =>
    `<div class="wiki-outline-item" data-line="${h.line}" style="padding-left:${(h.level - 1) * 0.7}rem">${esc(h.text)}</div>`).join('');
  panel.querySelectorAll('.wiki-outline-item').forEach(el => el.addEventListener('click', () => jumpToLine(+el.dataset.line, el.textContent)));
}
function jumpToLine(lineNo, text) {
  if (_docsMode === 'live' && _cm) {
    const view = _cm.view; const line = view.state.doc.line(Math.min(lineNo + 1, view.state.doc.lines));
    view.dispatch({ selection: { anchor: line.from }, scrollIntoView: true }); view.focus();
  } else if (_docsMode === 'source') {
    const src = $('wiki-source');
    const before = src.value.split('\n').slice(0, lineNo).join('\n');
    const pos = before.length + (lineNo ? 1 : 0);
    src.focus(); src.setSelectionRange(pos, pos);
    const lh = parseInt(getComputedStyle(src).lineHeight) || 20;
    src.scrollTop = Math.max(0, lineNo * lh - 60);
  }
  const pv = $('wiki-preview');
  const h = [...pv.querySelectorAll('h1,h2,h3,h4,h5,h6')].find(x => x.textContent.trim() === text.trim());
  if (h) h.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── properties / frontmatter editor ──────────────────────────────────────────
let _propsRows = [];
async function toggleProps() {
  const p = $('wiki-props'); if (!p) return;
  const show = p.style.display === 'none';
  p.style.display = show ? 'block' : 'none';
  $('wiki-props-btn')?.classList.toggle('active', show);
  if (show) await loadProps();
}
async function loadProps() {
  const p = $('wiki-props'); if (!p) return;
  if (!_cur) { p.innerHTML = '<div class="wiki-outline-empty">open a doc first</div>'; return; }
  await flushSave();
  let props = {};
  try { props = (await fetch(`/api/vault-md/properties?path=${encodeURIComponent(_cur)}`).then(r => r.json())).properties || {}; }
  catch { p.innerHTML = '<div class="wiki-outline-empty">failed to load</div>'; return; }
  _propsRows = Object.entries(props).map(([k, v]) => ({ key: k, value: Array.isArray(v) ? v.join(', ') : String(v), isList: Array.isArray(v) }));
  renderProps();
}
function renderProps() {
  const p = $('wiki-props'); if (!p) return;
  const rows = _propsRows.map((r, i) => `
    <div class="wiki-prop-row" data-i="${i}">
      <input class="wiki-prop-key" value="${esc(r.key)}" placeholder="property" spellcheck="false">
      <input class="wiki-prop-val" value="${esc(r.value)}" placeholder="value (comma = list)" spellcheck="false">
      <button class="icon-btn wiki-prop-del" title="remove">×</button>
    </div>`).join('');
  p.innerHTML = `<div class="wiki-outline-head">properties</div>${rows || '<div class="wiki-outline-empty">no properties yet</div>'}
    <div class="wiki-prop-actions">
      <button class="btn" id="wiki-prop-add">+ property</button>
      <button class="btn primary" id="wiki-prop-save">save</button>
    </div>`;
  p.querySelectorAll('.wiki-prop-row').forEach(row => {
    const i = +row.dataset.i;
    row.querySelector('.wiki-prop-key').addEventListener('input', e => _propsRows[i].key = e.target.value);
    row.querySelector('.wiki-prop-val').addEventListener('input', e => _propsRows[i].value = e.target.value);
    row.querySelector('.wiki-prop-del').addEventListener('click', () => { _propsRows.splice(i, 1); renderProps(); });
  });
  $('wiki-prop-add')?.addEventListener('click', () => { _propsRows.push({ key: '', value: '', isList: false }); renderProps(); });
  $('wiki-prop-save')?.addEventListener('click', saveProps);
}
async function saveProps() {
  if (!_cur) return;
  await flushSave();
  const props = {};
  for (const r of _propsRows) {
    const k = (r.key || '').trim(); if (!k) continue;
    const v = (r.value || '').trim();
    props[k] = (r.isList || v.includes(',')) ? v.split(',').map(s => s.trim()).filter(Boolean) : v;
  }
  try {
    await fetch('/api/vault-md/properties', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: _cur, properties: props }) });
    const d = await fetch(`/api/vault-md/file?path=${encodeURIComponent(_cur)}`).then(r => r.json());
    setEditor(d.content || '');
    await loadProps();
    toast('properties saved', 'success');
  } catch { toast('failed to save properties', 'error'); }
}

// ── note query (dataview-lite) ───────────────────────────────────────────────
const _QOPS = ['eq', 'ne', 'contains', 'gt', 'lt', 'exists', 'missing'];
let _qFilters = [{ field: 'status', op: 'eq', value: '' }];
let _qSort = { field: '', dir: 'asc' };
function toggleQuery() {
  const p = $('wiki-query'); if (!p) return;
  const show = p.style.display === 'none';
  p.style.display = show ? 'block' : 'none';
  $('wiki-query-btn')?.classList.toggle('active', show);
  if (show) renderQuery();
}
function renderQuery() {
  const p = $('wiki-query'); if (!p) return;
  const opOpts = (sel) => _QOPS.map(o => `<option${o === sel ? ' selected' : ''}>${o}</option>`).join('');
  const rows = _qFilters.map((f, i) => `
    <div class="wiki-q-row" data-i="${i}">
      <input class="wiki-q-field" value="${esc(f.field)}" placeholder="field / tag / folder" spellcheck="false">
      <select class="wiki-q-op">${opOpts(f.op)}</select>
      <input class="wiki-q-val" value="${esc(f.value)}" placeholder="value" spellcheck="false">
      <button class="icon-btn wiki-q-del" title="remove">×</button>
    </div>`).join('');
  p.innerHTML = `<div class="wiki-outline-head">query notes</div>${rows}
    <div class="wiki-q-actions">
      <button class="btn" id="wiki-q-add">+ filter</button>
      <input class="wiki-q-sort" id="wiki-q-sort" value="${esc(_qSort.field)}" placeholder="sort by field" spellcheck="false">
      <select id="wiki-q-dir"><option${_qSort.dir === 'asc' ? ' selected' : ''}>asc</option><option${_qSort.dir === 'desc' ? ' selected' : ''}>desc</option></select>
      <button class="btn primary" id="wiki-q-run">run</button>
    </div>
    <div class="wiki-q-results" id="wiki-q-results"></div>`;
  p.querySelectorAll('.wiki-q-row').forEach(row => {
    const i = +row.dataset.i;
    row.querySelector('.wiki-q-field').addEventListener('input', e => _qFilters[i].field = e.target.value);
    row.querySelector('.wiki-q-op').addEventListener('change', e => _qFilters[i].op = e.target.value);
    row.querySelector('.wiki-q-val').addEventListener('input', e => _qFilters[i].value = e.target.value);
    row.querySelector('.wiki-q-del').addEventListener('click', () => { _qFilters.splice(i, 1); if (!_qFilters.length) _qFilters.push({ field: '', op: 'eq', value: '' }); renderQuery(); });
  });
  $('wiki-q-add')?.addEventListener('click', () => { _qFilters.push({ field: '', op: 'eq', value: '' }); renderQuery(); });
  $('wiki-q-sort')?.addEventListener('input', e => _qSort.field = e.target.value);
  $('wiki-q-dir')?.addEventListener('change', e => _qSort.dir = e.target.value);
  $('wiki-q-run')?.addEventListener('click', runQuery);
}
async function runQuery() {
  const filters = _qFilters.filter(f => (f.field || '').trim());
  const body = { filters, limit: 200 };
  if (_qSort.field.trim()) body.sort = { field: _qSort.field.trim(), dir: _qSort.dir };
  const box = $('wiki-q-results'); if (box) box.innerHTML = '<div class="wiki-outline-empty">…</div>';
  let d;
  try { d = await api('/api/vault-md/query', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }); }
  catch { if (box) box.innerHTML = '<div class="wiki-outline-empty">query failed</div>'; return; }
  if (!box) return;
  if (!d.results.length) { box.innerHTML = '<div class="wiki-outline-empty">no matches</div>'; return; }
  box.innerHTML = `<div class="wiki-q-count">${d.count} note${d.count !== 1 ? 's' : ''}</div>` + d.results.map(r => {
    const meta = Object.entries(r.props).slice(0, 3).map(([k, v]) => `${esc(k)}: ${esc(Array.isArray(v) ? v.join(', ') : v)}`).join(' · ');
    return `<div class="wiki-q-result" data-path="${esc(r.path)}"><span class="wiki-q-name">${esc(r.name)}</span>${meta ? `<span class="wiki-q-meta">${meta}</span>` : ''}</div>`;
  }).join('');
  box.querySelectorAll('.wiki-q-result').forEach(el => el.addEventListener('click', () => openFile(el.dataset.path)));
}

async function openDaily() {
  const d = new Date();
  const name = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  await fetch('/api/vault-md/file', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: name, content: `# ${name}\n\n` }) });
  await loadTree();
  openFile(name + '.md');
}

// weekly / monthly review notes — server picks the path (ISO week) + seeds a template
async function openPeriodic(kind) {
  try {
    const d = await api('/api/vault-md/periodic', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ kind }) });
    await loadTree();
    openFile(d.path);
  } catch (e) { toast(e.message || `couldn't open ${kind} note`, 'error'); }
}

function queueSave() {
  if (!_cur) return;
  $('wiki-save-status').textContent = 'saving…';
  clearTimeout(_saveT);
  _saveT = setTimeout(doSave, 600);
}
async function doSave() {
  clearTimeout(_saveT); _saveT = 0;
  if (!_cur) return;
  try {
    await fetch('/api/vault-md/file', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: _cur, content: getEditor() }) });
    $('wiki-save-status').textContent = 'saved';
    delete _embedCache[_cur.split('/').pop().replace(/\.md$/, '').toLowerCase()];
    loadBacklinks();
  } catch { $('wiki-save-status').textContent = 'save failed'; }
}
async function flushSave() { if (_saveT) await doSave(); }

async function loadBacklinks() {
  if (!_cur) return;
  const name = _cur.split('/').pop().replace(/\.md$/, '');
  const el = $('wiki-backlinks'); if (!el) return;
  try {
    const [bl, ul] = await Promise.all([
      fetch(`/api/vault-md/backlinks?name=${encodeURIComponent(name)}`).then(r => r.json()).catch(() => ({ backlinks: [] })),
      fetch(`/api/vault-md/unlinked?name=${encodeURIComponent(name)}`).then(r => r.json()).catch(() => ({ mentions: [] })),
    ]);
    const links = bl.backlinks || [], ment = ul.mentions || [];
    const row = b => `<div class="wiki-bl" data-path="${esc(b.path)}"><b>${esc(b.name)}</b> <span>${esc(b.context)}</span></div>`;
    let html = '';
    if (links.length) html += `<div class="wiki-bl-head">${links.length} backlink${links.length > 1 ? 's' : ''}</div>` + links.map(row).join('');
    if (ment.length) html += `<div class="wiki-bl-head wiki-bl-unlinked">${ment.length} unlinked mention${ment.length > 1 ? 's' : ''}</div>` + ment.map(row).join('');
    el.innerHTML = html || '<span class="wiki-bl-empty">no backlinks</span>';
    el.querySelectorAll('.wiki-bl').forEach(b => b.addEventListener('click', () => openFile(b.dataset.path)));
  } catch {}
}

async function exportDocx() {
  if (!_cur) { toast('open a doc first', 'error'); return; }
  await flushSave();
  try {
    const r = await fetch(`/api/vault-md/export-docx?path=${encodeURIComponent(_cur)}`);
    if (!r.ok) throw new Error();
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = _cur.split('/').pop().replace(/\.md$/, '') + '.docx';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast('exported .docx', 'success');
  } catch { toast('export failed', 'error'); }
}

// ── export menu (docx / html / pdf) ─────────────────────────────────────────
function openExportMenu(btn) {
  document.getElementById('wiki-export-pop')?.remove();
  if (!_cur) { toast('open a doc first', 'error'); return; }
  const pop = document.createElement('div');
  pop.id = 'wiki-export-pop'; pop.className = 'wiki-menu-pop';
  pop.innerHTML = `<button class="wmp-item" data-x="docx">word (.docx)</button>`
    + `<button class="wmp-item" data-x="html">html</button>`
    + `<button class="wmp-item" data-x="pdf">pdf / print</button>`;
  document.body.appendChild(pop);
  const r = btn.getBoundingClientRect();
  pop.style.left = Math.min(r.left, window.innerWidth - 170) + 'px';
  pop.style.top = (r.bottom + 4) + 'px';
  pop.querySelectorAll('.wmp-item').forEach(b => b.addEventListener('click', () => {
    pop.remove();
    if (b.dataset.x === 'docx') exportDocx();
    else if (b.dataset.x === 'html') exportHtml();
    else exportPdf();
  }));
  setTimeout(() => document.addEventListener('mousedown', function h(ev) { if (!pop.contains(ev.target) && ev.target !== btn) { pop.remove(); document.removeEventListener('mousedown', h); } }), 0);
}
function _exportDoc(title) {
  renderPreview();
  const body = ($('wiki-preview').innerHTML || '').replace(/(src|href)="\//g, `$1="${location.origin}/`);
  const css = `*{box-sizing:border-box}body{max-width:760px;margin:2rem auto;padding:0 1.5rem;font-family:Inter,-apple-system,system-ui,sans-serif;line-height:1.7;color:#1a1a1a;background:#fff}
h1,h2,h3,h4{line-height:1.25;margin:1.4em 0 .5em;font-weight:600}h1{font-size:1.9rem}h2{font-size:1.5rem}h3{font-size:1.25rem}
p{margin:.7em 0}a{color:#2563eb;text-decoration:none}code{font-family:ui-monospace,Menlo,monospace;background:#f3f3f3;padding:.1em .3em;border-radius:3px;font-size:.9em}
pre{background:#f6f8fa;padding:1rem;border-radius:6px;overflow:auto}pre code{background:none;padding:0}
blockquote{border-left:3px solid #ddd;margin:1em 0;padding:.2em 0 .2em 1em;color:#555}
table{border-collapse:collapse;margin:1em 0}th,td{border:1px solid #ddd;padding:.4em .7em}
img{max-width:100%}mark{background:#fef08a;padding:0 .15em}ul,ol{padding-left:1.4em}.md-task{list-style:none}
hr{border:none;border-top:1px solid #ddd;margin:1.5em 0}.code-block-header,.code-copy,.code-run{display:none}
.md-callout{border-left:3px solid #888;padding:.5em 1em;margin:1em 0;background:#f7f7f7;border-radius:4px}
.md-frontmatter{font-size:.85em;color:#666;border-bottom:1px solid #eee;padding-bottom:.6em;margin-bottom:1em}
.md-fm-row{display:flex;gap:.5em}.md-fm-key{font-weight:600;min-width:90px}
@media print{body{margin:0;max-width:none}}`;
  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(title)}</title><style>${css}</style></head><body>${body}</body></html>`;
}
function exportHtml() {
  if (!_cur) { toast('open a doc first', 'error'); return; }
  const title = _cur.split('/').pop().replace(/\.md$/, '');
  const blob = new Blob([_exportDoc(title)], { type: 'text/html' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = title + '.html'; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  toast('exported .html', 'success');
}
function exportPdf() {
  if (!_cur) { toast('open a doc first', 'error'); return; }
  const title = _cur.split('/').pop().replace(/\.md$/, '');
  const w = window.open('', '_blank');
  if (!w) { toast('allow popups to export pdf', 'error'); return; }
  w.document.write(_exportDoc(title));
  w.document.close();
  w.onload = () => setTimeout(() => { w.focus(); w.print(); }, 400);
}

// ── new from template ────────────────────────────────────────────────────────
async function openTemplateMenu(btn) {
  document.getElementById('wiki-tmpl-pop')?.remove();
  let tmpls = [];
  try { tmpls = (await fetch('/api/vault-md/templates').then(r => r.json())).templates || []; } catch {}
  const pop = document.createElement('div');
  pop.id = 'wiki-tmpl-pop'; pop.className = 'wiki-menu-pop';
  pop.innerHTML = `<div class="wmp-label">new from template</div>`
    + (tmpls.length ? tmpls.map(t => `<button class="wmp-item" data-name="${esc(t.name)}">${esc(t.name)}</button>`).join('')
      : '<div class="wmp-empty">no templates — add .md files to _templates/</div>');
  document.body.appendChild(pop);
  const r = btn.getBoundingClientRect();
  pop.style.left = Math.min(r.left, window.innerWidth - 200) + 'px';
  pop.style.top = (r.bottom + 4) + 'px';
  pop.querySelectorAll('.wmp-item').forEach(b => b.addEventListener('click', () => { pop.remove(); newFromTemplate(tmpls.find(x => x.name === b.dataset.name)); }));
  setTimeout(() => document.addEventListener('mousedown', function h(ev) { if (!pop.contains(ev.target) && ev.target !== btn) { pop.remove(); document.removeEventListener('mousedown', h); } }), 0);
}
function _subTokens(s, title) {
  const d = new Date();
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  return (s || '').replace(/\{\{title\}\}/g, title.replace(/\.md$/, '')).replace(/\{\{date\}\}/g, date).replace(/\{\{time\}\}/g, time);
}
async function newFromTemplate(t) {
  if (!t) return;
  const name = await dlgPrompt('doc name (folders ok):');
  if (!name?.trim()) return;
  const content = _subTokens(t.content, name.trim().split('/').pop());
  await fetch('/api/vault-md/file', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: name.trim(), content }) });
  await loadTree();
  openFile(name.trim().endsWith('.md') ? name.trim() : name.trim() + '.md');
}

// ── import: from a file, or from a YouTube link ──────────────────────────────
function openImportMenu(btn) {
  document.getElementById('wiki-import-pop')?.remove();
  const pop = document.createElement('div');
  pop.id = 'wiki-import-pop'; pop.className = 'wiki-menu-pop';
  pop.innerHTML = `<button class="wmp-item" data-x="file">from file…</button><button class="wmp-item" data-x="yt">from YouTube link…</button>`;
  document.body.appendChild(pop);
  const r = btn.getBoundingClientRect();
  pop.style.left = Math.min(r.left, window.innerWidth - 190) + 'px';
  pop.style.top = (r.bottom + 4) + 'px';
  pop.querySelectorAll('.wmp-item').forEach(b => b.addEventListener('click', () => {
    pop.remove();
    if (b.dataset.x === 'file') $('wiki-import-input')?.click();
    else importYoutube();
  }));
  setTimeout(() => document.addEventListener('mousedown', function h(ev) { if (!pop.contains(ev.target) && ev.target !== btn) { pop.remove(); document.removeEventListener('mousedown', h); } }), 0);
}

async function importYoutube() {
  const url = await dlgPrompt('YouTube URL:');
  if (!url?.trim()) return;
  toast('fetching transcript…', '');
  try {
    const d = await api('/api/vault-md/youtube', { method: 'POST', body: { url: url.trim() } });
    await loadTree();
    await openFile(d.path);
    toast(d.summarized ? 'imported + summarized' : 'imported transcript', 'success');
  } catch (e) { toast(e.message || 'youtube import failed', 'error'); }
}

// ── import a document (.md/.txt/.docx/.html/.pdf → markdown doc) ─────────────
async function importDoc(e) {
  const file = e.target.files?.[0];
  e.target.value = '';   // let the same file be picked again later
  if (!file) return;
  toast(`importing ${file.name}…`, '');
  const fd = new FormData();
  fd.append('file', file, file.name);
  try {
    const d = await api('/api/vault-md/import', { method: 'POST', body: fd });
    await loadTree();
    await openFile(d.path);
    toast(`imported ${d.name}`, 'success');
  } catch (e) { toast(e.message || 'import failed', 'error'); }
}

// ── tasks rollup (every - [ ] across the vault) ──────────────────────────────
function toggleTaskRoll() {
  const p = $('wiki-taskroll'); if (!p) return;
  const show = p.style.display === 'none';
  p.style.display = show ? 'block' : 'none';
  $('wiki-taskroll-btn')?.classList.toggle('active', show);
  if (show) loadTaskRoll();
}
async function loadTaskRoll() {
  const p = $('wiki-taskroll'); if (!p) return;
  p.innerHTML = '<div class="wiki-tr-head">loading…</div>';
  let tasks = [];
  try { tasks = (await fetch('/api/vault-md/tasks').then(r => r.json())).tasks || []; }
  catch { p.innerHTML = '<div class="wiki-tr-head">failed to load</div>'; return; }
  if (!tasks.length) { p.innerHTML = '<div class="wiki-tr-head">no tasks — add - [ ] items in your docs</div>'; return; }
  const open = tasks.filter(t => !t.done), done = tasks.filter(t => t.done);
  const row = t => `<div class="wiki-tr-item${t.done ? ' done' : ''}" data-path="${esc(t.path)}" data-line="${t.line}">
    <span class="chk" data-toggle aria-checked="${t.done ? 'true' : 'false'}"></span>
    <span class="wiki-tr-text">${esc(t.text)}</span><span class="wiki-tr-doc">${esc(t.name)}</span></div>`;
  p.innerHTML = `<div class="wiki-tr-head">${open.length} open · ${done.length} done</div>` + open.map(row).join('') + done.map(row).join('');
  p.querySelectorAll('.wiki-tr-item').forEach(el => {
    const path = el.dataset.path, line = +el.dataset.line;
    const chk = el.querySelector('[data-toggle]');
    chk.addEventListener('click', async e => {
      e.stopPropagation();
      const done = chk.getAttribute('aria-checked') !== 'true';
      chk.setAttribute('aria-checked', done ? 'true' : 'false');
      if (_cur === path) await flushSave();   // don't clobber unsaved edits to the open doc
      try {
        const r = await fetch('/api/vault-md/task', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path, line, done }) });
        if (!r.ok) throw new Error();
        el.classList.toggle('done', done);
        if (_cur === path) { const d = await fetch(`/api/vault-md/file?path=${encodeURIComponent(path)}`).then(r => r.json()); setEditor(d.content || ''); }
      } catch { toast('failed to update task', 'error'); chk.setAttribute('aria-checked', done ? 'false' : 'true'); }
    });
    el.querySelector('.wiki-tr-text').addEventListener('click', async () => { await openFile(path); jumpToLine(line, ''); });
  });
}

// ── quick switcher (Ctrl/Cmd+O) ──────────────────────────────────────────────
let _qsOpen = false;
async function openQuickSwitcher() {
  if (_qsOpen) return; _qsOpen = true;
  let names = [];
  try { names = (await fetch('/api/vault-md/names').then(r => r.json())).names || []; } catch {}
  const ov = document.createElement('div');
  ov.className = 'wiki-qs-overlay'; ov.id = 'wiki-qs';
  ov.innerHTML = `<div class="wiki-qs-box"><input class="wiki-qs-input" type="text" placeholder="jump to doc… (Enter creates if missing)" spellcheck="false"><div class="wiki-qs-list"></div></div>`;
  document.body.appendChild(ov);
  const inp = ov.querySelector('.wiki-qs-input'), list = ov.querySelector('.wiki-qs-list');
  let sel = 0, filtered = names.slice();
  const render = () => {
    list.innerHTML = filtered.slice(0, 50).map((n, i) => `<div class="wiki-qs-item${i === sel ? ' active' : ''}" data-i="${i}">${esc(n)}</div>`).join('')
      || '<div class="wiki-qs-empty">no match — Enter to create</div>';
    list.querySelectorAll('.wiki-qs-item').forEach(el => el.addEventListener('mousedown', e => { e.preventDefault(); pick(+el.dataset.i); }));
  };
  const close = () => { _qsOpen = false; ov.remove(); };
  const pick = i => { const name = filtered[i]; close(); if (name) openByName(name); };
  inp.addEventListener('input', () => {
    const q = inp.value.trim().toLowerCase();
    filtered = q ? names.filter(n => n.toLowerCase().includes(q)).sort((a, b) => (a.toLowerCase().startsWith(q) ? 0 : 1) - (b.toLowerCase().startsWith(q) ? 0 : 1)) : names.slice();
    sel = 0; render();
  });
  inp.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, filtered.length - 1); render(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); render(); }
    else if (e.key === 'Enter') { e.preventDefault(); if (filtered.length) pick(sel); else { const v = inp.value.trim(); if (v) { close(); openByName(v); } } }
    else if (e.key === 'Escape') { e.preventDefault(); close(); }
  });
  ov.addEventListener('mousedown', e => { if (e.target === ov) close(); });
  render(); inp.focus();
}

async function newNote() {
  const name = await dlgPrompt('doc name (folders ok, e.g. ideas/new):');
  if (!name?.trim()) return;
  await fetch('/api/vault-md/file', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: name.trim() }) });
  await loadTree();
  openFile(name.trim().endsWith('.md') ? name.trim() : name.trim() + '.md');
}
async function deleteCurrent() {
  if (!_cur) return;
  if (!await dlgConfirm(`delete ${_cur}?`)) return;
  await fetch(`/api/vault-md/file?path=${encodeURIComponent(_cur)}`, { method: 'DELETE' });
  _resetEditor();
  loadTree();
}

// ── [[ autocomplete (source mode) ──────────────────────────────────────────
let _acItems = [], _acSel = 0, _acStart = -1;
async function autocomplete() {
  const src = $('wiki-source');
  if (!src || _docsMode !== 'source') return hideAc();
  const v = src.value, pos = src.selectionStart;
  const open = v.lastIndexOf('[[', pos - 1);
  if (open < 0 || v.slice(open, pos).includes(']]')) return hideAc();
  const q = v.slice(open + 2, pos);
  if (q.includes('\n') || q.includes('[')) return hideAc();
  _acStart = open;
  const res = await fetch(`/api/vault-md/search?q=${encodeURIComponent(q)}`).then(r => r.json()).catch(() => ({ results: [] }));
  _acItems = res.results || [];
  if (!_acItems.length) return hideAc();
  _acSel = 0;
  renderAc();
}
function renderAc() {
  const box = $('wiki-autocomplete');
  box.innerHTML = _acItems.map((it, i) => `<div class="wiki-ac-item${i === _acSel ? ' active' : ''}" data-i="${i}">${esc(it.name)}</div>`).join('');
  box.style.display = 'block';
  box.querySelectorAll('.wiki-ac-item').forEach(el => el.addEventListener('mousedown', e => { e.preventDefault(); pickAc(+el.dataset.i); }));
}
function hideAc() { const b = $('wiki-autocomplete'); if (b) b.style.display = 'none'; _acItems = []; }
function acKeydown(e) {
  if ($('wiki-autocomplete').style.display !== 'block' || !_acItems.length) return;
  if (e.key === 'ArrowDown') { e.preventDefault(); _acSel = (_acSel + 1) % _acItems.length; renderAc(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); _acSel = (_acSel - 1 + _acItems.length) % _acItems.length; renderAc(); }
  else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pickAc(_acSel); }
  else if (e.key === 'Escape') { e.preventDefault(); hideAc(); }
}
function pickAc(i) {
  const src = $('wiki-source');
  const name = _acItems[i].name;
  const v = src.value, pos = src.selectionStart;
  const caret = _acStart + name.length + 4;
  src.value = v.slice(0, _acStart) + `[[${name}]]` + v.slice(pos);
  src.setSelectionRange(caret, caret);
  hideAc();
  onSourceInput();
}

// docs: file tree + a CodeMirror live-preview editor + rendered preview, with
// [[wikilinks]], backlinks, embeds, tags, graph, outline, history.
//
// modes (mode button cycles): live = CodeMirror WYSIWYG (markdown symbols hidden,
// styled inline, symbols reveal on the cursor's line) · source = raw markdown
// textarea · preview = fully rendered. CodeMirror edits plain markdown text
// directly (no lossy round-trip), so a save can never corrupt the file.
import { mdToHtml, toast, enhanceMarkdown, api } from './util.js';
import { prompt as dlgPrompt, confirm as dlgConfirm } from './dialog.js';
import { initCanvas, openCanvas, setCanvasNoteOpener } from './canvas.js';

let _cur = null;
let _saveT = 0;
let _hoverT = 0;
let _bookmarks = [];
let _tabs = [];
let _split = false, _splitDoc = null;
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
        if (!_applyingExternal) { queueSave(); slashDetect(); }
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
// img toolbar button → small dialog: paste a URL or upload a file from the device.
// url → ![](url); upload → ![[asset]] (goes through the same vault asset route as paste/drop)
function openImageDialog(btn) {
  document.getElementById('wiki-img-pop')?.remove();
  if (!_cur) { toast('open a doc first', 'error'); return; }
  const pop = document.createElement('div');
  pop.id = 'wiki-img-pop'; pop.className = 'wiki-menu-pop wiki-img-pop';
  pop.innerHTML = `<input id="wiki-img-url" type="text" placeholder="paste image URL…" autocomplete="off">
    <div class="wip-actions">
      <button id="wiki-img-insert" class="wmp-item wip-primary">insert</button>
      <button id="wiki-img-upload" class="wmp-item">upload from device</button>
    </div>
    <input id="wiki-img-file" type="file" accept="image/*" hidden>`;
  document.body.appendChild(pop);
  const r = (btn || $('docs-toolbar')).getBoundingClientRect();
  pop.style.left = Math.min(r.left, window.innerWidth - 290) + 'px';
  pop.style.top = (r.bottom + 5) + 'px';
  const url = pop.querySelector('#wiki-img-url');
  url.focus();
  const close = () => pop.remove();
  const doUrl = () => { const v = url.value.trim(); if (!v) { toast('enter an image url', 'error'); return; } insertBlock(`![](${v})`); close(); };
  pop.querySelector('#wiki-img-insert').addEventListener('click', doUrl);
  url.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); doUrl(); } else if (e.key === 'Escape') close(); });
  const file = pop.querySelector('#wiki-img-file');
  pop.querySelector('#wiki-img-upload').addEventListener('click', () => file.click());
  file.addEventListener('change', async () => {
    const f = file.files?.[0]; if (!f) return;
    try { const path = await uploadImage(f); insertBlock(`![[${path}]]`); } catch {}
    close();
  });
  setTimeout(() => document.addEventListener('mousedown', function h(ev) { if (!pop.contains(ev.target) && ev.target !== btn) { close(); document.removeEventListener('mousedown', h); } }), 0);
}

// ── docs settings (3t): AI status + which model the docs AI uses ─────────────
async function openDocsSettings(btn) {
  document.getElementById('wiki-docs-settings-pop')?.remove();
  const [eps, settings] = await Promise.all([
    fetch('/api/models').then(r => r.json()).catch(() => []),
    fetch('/api/settings').then(r => r.json()).catch(() => ({})),
  ]);
  const models = [];
  (eps || []).forEach(ep => (ep.models || []).forEach(m => models.push({ ep: ep.name || ep.base_url, model: m })));
  const cur = (settings.docs_ai_model || '').trim();
  const ready = models.length > 0;
  const usingModel = (ready && cur && models.some(m => m.model === cur)) ? cur : (models[0]?.model || '');
  const pop = document.createElement('div');
  pop.id = 'wiki-docs-settings-pop'; pop.className = 'wiki-menu-pop wiki-docs-settings-pop';
  pop.innerHTML = `<div class="wds-title">docs settings</div>
    <div class="wds-status ${ready ? 'ok' : 'off'}"><span class="wds-dot"></span>${ready ? `AI ready · using <b>${esc(usingModel || '—')}</b>` : 'no model — add one in settings → models'}</div>
    <div class="wds-label">AI model for docs (rewrite / ask / to-dos)</div>
    <div class="wds-models">${ready
      ? models.map(m => `<button class="wds-model${m.model === usingModel ? ' on' : ''}" data-m="${esc(m.model)}"><span class="wds-m-name">${esc(m.model)}</span><span class="wds-m-ep">${esc(m.ep)}</span></button>`).join('')
      : '<div class="wmp-empty">connect a model endpoint in the main settings first</div>'}</div>`;
  document.body.appendChild(pop);
  const r = btn.getBoundingClientRect();
  pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 280)) + 'px';
  pop.style.top = (r.bottom + 5) + 'px';
  pop.querySelectorAll('.wds-model').forEach(b => b.addEventListener('click', async () => {
    await fetch('/api/settings', { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ docs_ai_model: b.dataset.m }) });
    pop.querySelectorAll('.wds-model').forEach(x => x.classList.toggle('on', x === b));
    pop.querySelector('.wds-status b') && (pop.querySelector('.wds-status b').textContent = b.dataset.m);
    toast('docs AI model set', 'success');
  }));
  setTimeout(() => document.addEventListener('mousedown', function h(ev) { if (!pop.contains(ev.target) && ev.target !== btn) { pop.remove(); document.removeEventListener('mousedown', h); } }), 0);
}

// ── custom right-click menu (3i): cut/copy/paste, format, headings, AI on selection ──
function _docSel() {
  if (_docsMode === 'live' && _cm) {
    const r = _cm.view.state.selection.main;
    return { text: _cm.view.state.sliceDoc(r.from, r.to), from: r.from, to: r.to };
  }
  const ta = $('wiki-source');
  if (ta) return { text: ta.value.slice(ta.selectionStart, ta.selectionEnd), from: ta.selectionStart, to: ta.selectionEnd };
  return { text: '', from: 0, to: 0 };
}
function _docRestoreSel(sel) {
  if (_docsMode === 'live' && _cm) { _cm.view.dispatch({ selection: { anchor: sel.from, head: sel.to } }); _cm.view.focus(); }
}
function _docReplaceSel(sel, text) {
  if (_docsMode === 'live' && _cm) {
    _cm.view.dispatch({ changes: { from: sel.from, to: sel.to, insert: text }, selection: { anchor: sel.from + text.length } });
    _cm.view.focus();
  } else {
    const ta = $('wiki-source'); if (!ta) return;
    ta.setRangeText(text, sel.from, sel.to, 'end'); ta.dispatchEvent(new Event('input')); ta.focus();
  }
}
async function _docPaste(sel) {
  try { const t = await navigator.clipboard.readText(); if (t) _docReplaceSel(sel, t); }
  catch { toast('paste needs clipboard access', 'error'); }
}
async function _aiSnippet(action, sel) {
  if (!sel.text.trim()) { toast('select some text first', 'error'); return; }
  toast(`ai ${action}…`, '');
  try {
    const r = await fetch('/api/vault-md/ai-snippet', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: sel.text, action }) });
    if (!r.ok) { toast('ai unavailable — add a model in settings', 'error'); return; }
    const d = await r.json();
    if (d.text) { _docReplaceSel(sel, d.text); toast('done', 'success'); }
    else toast('ai returned nothing', 'error');
  } catch { toast('ai failed', 'error'); }
}
function openDocsContextMenu(e) {
  e.preventDefault();
  document.getElementById('docs-ctx')?.remove();
  const sel = _docSel();
  const has = !!sel.text.trim();
  const menu = document.createElement('div');
  menu.id = 'docs-ctx'; menu.className = 'ctx-menu docs-ctx';
  const it = (act, label, dis) => `<div class="ctx-item${dis ? ' ctx-dis' : ''}" data-act="${act}">${label}</div>`;
  menu.innerHTML =
    it('cut', 'cut', !has) + it('copy', 'copy', !has) + it('paste', 'paste') +
    '<div class="ctx-sep"></div>' +
    it('bold', 'bold') + it('italic', 'italic') + it('code', 'code') + it('link', 'link') +
    '<div class="ctx-sep"></div>' +
    it('h1', 'heading 1') + it('h2', 'heading 2') +
    '<div class="ctx-sep"></div><div class="ctx-label">ai</div>' +
    it('ai-rewrite', 'rewrite', !has) + it('ai-summarize', 'summarize', !has) + it('ai-fix', 'fix grammar', !has);
  document.body.appendChild(menu);
  menu.style.left = Math.min(e.clientX, window.innerWidth - 190) + 'px';
  menu.style.top = Math.min(e.clientY, window.innerHeight - menu.offsetHeight - 8) + 'px';
  const close = () => menu.remove();
  menu.querySelectorAll('.ctx-item:not(.ctx-dis)').forEach(b => b.addEventListener('mousedown', ev => {
    ev.preventDefault();
    const act = b.dataset.act; close();
    if (act === 'cut') document.execCommand('cut');
    else if (act === 'copy') document.execCommand('copy');
    else if (act === 'paste') _docPaste(sel);
    else if (act.startsWith('ai-')) _aiSnippet(act.slice(3), sel);
    else {
      _docRestoreSel(sel);
      if (act === 'bold') wrapSel('**', '**');
      else if (act === 'italic') wrapSel('*', '*');
      else if (act === 'code') wrapSel('`', '`');
      else if (act === 'link') insertLink();
      else if (act === 'h1') toggleLinePrefix('# ');
      else if (act === 'h2') toggleLinePrefix('## ');
    }
  }));
  setTimeout(() => document.addEventListener('mousedown', function h(ev) { if (!menu.contains(ev.target)) { close(); document.removeEventListener('mousedown', h); } }), 0);
}
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
  link: () => insertLink(), image: (b) => openImageDialog(b), wiki: () => insertWiki(),
  hr: () => insertBlock('\n---\n'),   // blank line before so '---' is a divider, not a setext heading
  table: () => insertBlock('| {}col 1 | col 2 |\n| --- | --- |\n| a | b |'),
  codeblock: () => insertBlock('```\n{}\n```'),
  callout: () => insertBlock('> [!note] {}title\n> body'),
  toggle: () => insertBlock('> [!toggle] {}title\n> hidden body'),
  columns: () => insertBlock('::: columns\n{}left column\n+++\nright column\n:::'),
  math: () => insertBlock('$$\n{}\n$$'),
  mermaid: () => insertBlock('```mermaid\ngraph TD;\n  {}A --> B\n```'),
};
let _toolbarInited = false;
function initDocsToolbar() {
  const bar = $('docs-toolbar');
  if (!bar || _toolbarInited) return;
  _toolbarInited = true;
  bar.querySelectorAll('.dt-btn[data-fmt]').forEach(b =>
    b.addEventListener('mousedown', e => { e.preventDefault(); _FMT[b.dataset.fmt]?.(b); }));
  $('dt-color-btn')?.addEventListener('mousedown', e => { e.preventDefault(); _toggleColorPalette(e.currentTarget); });
}

export function initVault() {
  if (_inited) { loadTree(); return; }
  _inited = true;
  _loadBookmarks().then(_paintHome);
  $('wiki-view')?.classList.add('tree-hidden');   // sidebar always starts closed in a doc — open it with the ☰ toggle
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
  $('wiki-home-btn')?.addEventListener('click', () => { _resetEditor(); loadTree(); });   // back to docs home
  $('docs-home-search')?.addEventListener('input', _paintHome);
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
  $('wiki-ask-btn')?.addEventListener('click', toggleAsk);
  $('wiki-ask-go')?.addEventListener('click', runAsk);
  $('wiki-ask-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') runAsk(); });
  $('wiki-comments-btn')?.addEventListener('click', toggleComments);
  $('wiki-preview')?.addEventListener('mouseup', _onDocSelect);
  $('wiki-live')?.addEventListener('mouseup', _onDocSelect);   // 3m: comment from a live-mode selection too
  $('wiki-comment-fab')?.addEventListener('mousedown', e => { e.preventDefault(); _addCommentFromSelection(); });
  $('wiki-base-btn')?.addEventListener('click', toggleBase);
  initCanvas();
  setCanvasNoteOpener(openByName);
  // canvas / board / tasks live on the docs HOME now (3k), not the in-doc toolbar
  $('wiki-home-canvas')?.addEventListener('click', async () => {
    const name = await dlgPrompt('canvas name:', 'board');
    if (name) openCanvas(name);
  });
  { const cv = new URLSearchParams(location.search).get('canvas'); if (cv) setTimeout(() => openCanvas(cv), 300); }
  $('wiki-split-btn')?.addEventListener('click', toggleSplit);
  _initSplitDivider();
  _restoreTabs();
  $('wiki-home-board')?.addEventListener('click', openBoard);
  $('wiki-board-close')?.addEventListener('click', () => { $('wiki-board').style.display = 'none'; });
  $('wiki-todos-btn')?.addEventListener('click', e => openTodosExplainer(e.currentTarget));
  $('wiki-home-tasks')?.addEventListener('click', toggleTaskRoll);
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
  $('wiki-graph-local')?.addEventListener('click', () => {
    _graphLocal = !_graphLocal;
    $('wiki-graph-local').classList.toggle('active', _graphLocal);
    fetchGraph();
  });
  let _gfT = 0;
  $('wiki-graph-filter')?.addEventListener('input', () => { clearTimeout(_gfT); _gfT = setTimeout(fetchGraph, 200); });
  $('wiki-docs-settings')?.addEventListener('click', e => openDocsSettings(e.currentTarget));
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
  // hover preview of a linked note (2a)
  $('wiki-preview')?.addEventListener('mouseover', e => {
    const a = e.target.closest('.wikilink');
    if (!a || !a.dataset.note) return;
    clearTimeout(_hoverT);
    _hoverT = setTimeout(() => showLinkPreview(a), 350);
  });
  $('wiki-preview')?.addEventListener('mouseout', e => {
    if (e.target.closest('.wikilink')) { clearTimeout(_hoverT); hideLinkPreview(); }
  });
  // live-editor links (3e): single click edits (CM default); ⌘/ctrl-click opens; hover shows the target
  $('wiki-live')?.addEventListener('mousedown', e => {
    const a = e.target.closest('a.cm-link, .wikilink');
    if (a && (e.metaKey || e.ctrlKey)) {
      e.preventDefault(); e.stopPropagation();
      if (a.classList.contains('wikilink') && a.dataset.note) openByName(a.dataset.note);
      else if (a.getAttribute('href')) window.open(a.getAttribute('href'), '_blank', 'noopener');
    }
  }, true);
  $('wiki-live')?.addEventListener('mouseover', e => {
    const a = e.target.closest('a.cm-link'); if (!a) return;
    clearTimeout(_hoverT); _hoverT = setTimeout(() => showUrlTip(a), 280);
  });
  $('wiki-live')?.addEventListener('mouseout', e => {
    if (e.target.closest('a.cm-link')) { clearTimeout(_hoverT); hideUrlTip(); }
  });
  $('wiki-live')?.addEventListener('contextmenu', openDocsContextMenu);
  $('wiki-source')?.addEventListener('contextmenu', openDocsContextMenu);
  $('wiki-empty-new')?.addEventListener('click', newNote);
  $('wiki-empty-today')?.addEventListener('click', openDaily);
  $('wiki-ai-send')?.addEventListener('click', aiEdit);
  $('wiki-ai-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') aiEdit(); });

  const ta = $('wiki-source');
  if (ta) {
    ta.addEventListener('input', onSourceInput);
    ta.addEventListener('keydown', onSourceKeydown);
    ta.addEventListener('blur', () => setTimeout(hideAc, 120));
    ta.addEventListener('click', () => hideAc());
  }
  // slash menu nav: capture phase so it beats CM6's own keymap while the menu is open
  document.addEventListener('keydown', _slashKeydown, true);
  initDocsToolbar();
  applyDocsMode();
  loadTree();
  const qd = new URLSearchParams(location.search).get('doc');   // deep-link / refresh restore
  if (qd) openFile(qd);
}

// ── source (raw textarea) mode ───────────────────────────────────────────────
function onSourceInput() {
  if (!_cur) return;
  updateStats();
  queueSave();
  autocomplete();
  slashDetect();
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
let _homeDocs = [];
function renderRecent(items) {
  // docs home gallery — all docs as cards, newest first (google-docs style)
  _homeDocs = _flattenFiles(items).sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
  _paintHome();
}

function _fmtDate(mt) {
  if (!mt) return '';
  try { return new Date(mt * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }); }
  catch { return ''; }
}

const _DOC_ICON = '<svg class="docs-card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';

function _paintHome() {
  const el = $('wiki-empty-recent');
  if (!el) return;
  const q = ($('docs-home-search')?.value || '').toLowerCase().trim();
  const docs = q
    ? _homeDocs.filter(f => (f.name || '').toLowerCase().includes(q) || (f.path || '').toLowerCase().includes(q))
    : _homeDocs;
  if (!docs.length) {
    el.innerHTML = `<div class="docs-home-empty">${q ? 'no docs match' : 'no docs yet — make one with + new doc'}</div>`;
    return;
  }
  let head = '';
  if (!q && _bookmarks.length) {
    head = `<div class="docs-bookmarks" id="docs-bookmarks"><div class="docs-bookmarks-label">★ bookmarks</div>`
      + _bookmarks.map(b => `<button class="docs-bm" data-path="${esc(b.path)}">${esc(b.title || b.path)}</button>`).join('')
      + `</div>`;
  }
  el.innerHTML = head + docs.map(f => {
    const folder = f.path.includes('/') ? f.path.slice(0, f.path.lastIndexOf('/')) : '';
    const meta = [folder, _fmtDate(f.mtime)].filter(Boolean).join(' · ');
    const star = _isBookmarked(f.path) ? '★' : '☆';
    return `<div class="docs-card" data-path="${esc(f.path)}">${_DOC_ICON}
      <span class="docs-card-title">${esc(f.name)}</span>
      <span class="docs-card-meta">${esc(meta)}</span>
      <button class="docs-card-star${_isBookmarked(f.path) ? ' on' : ''}" data-bm="${esc(f.path)}" title="bookmark">${star}</button></div>`;
  }).join('');
  el.querySelectorAll('.docs-card').forEach(c => c.addEventListener('click', e => {
    if (e.target.closest('.docs-card-star')) return;   // star handled separately
    openFile(c.dataset.path);
  }));
  el.querySelectorAll('.docs-bm').forEach(b => b.addEventListener('click', () => openFile(b.dataset.path)));
  el.querySelectorAll('.docs-card-star').forEach(s => s.addEventListener('click', async e => {
    e.stopPropagation();
    await _bookmarkPath(s.dataset.bm);
    _paintHome();   // repaint so the star + bookmarks strip update
  }));
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
    el.innerHTML = _renderTagTree(d.tags || []);
    el.querySelectorAll('.wiki-tag').forEach(t => t.addEventListener('click', () => filterByTag(t.dataset.tag)));
    el.querySelectorAll('.wiki-tag-toggle').forEach(tg => tg.addEventListener('click', e => {
      e.stopPropagation();
      tg.closest('.wiki-tag-node')?.classList.toggle('collapsed');
      tg.textContent = tg.closest('.wiki-tag-node')?.classList.contains('collapsed') ? '▸' : '▾';
    }));
  } catch {}
}

// nest #a/b/c tags into a collapsible tree (2a)
function _tagTree(tags) {
  const root = { children: {}, count: 0, full: '' };
  for (const { tag, count } of tags) {
    let node = root, acc = '';
    const parts = String(tag).split('/');
    parts.forEach((p, i) => {
      acc = acc ? acc + '/' + p : p;
      node.children[p] = node.children[p] || { children: {}, count: 0, full: acc };
      node = node.children[p];
      if (i === parts.length - 1) node.count = count;
    });
  }
  return root;
}
function _tagNodeHtml(name, node, depth) {
  const kids = Object.entries(node.children);
  const pad = `style="padding-left:${depth * 0.7}rem"`;
  let h = '<div class="wiki-tag-node">';
  h += `<span class="wiki-tag${node.full === _activeTag ? ' active' : ''}" data-tag="${esc(node.full)}" ${pad}>`;
  if (kids.length) h += '<span class="wiki-tag-toggle">▾</span> ';
  h += `#${esc(name)}${node.count ? ` <em>${node.count}</em>` : ''}</span>`;
  if (kids.length) h += '<div class="wiki-tag-children">' + kids.map(([n, c]) => _tagNodeHtml(n, c, depth + 1)).join('') + '</div>';
  return h + '</div>';
}
function _renderTagTree(tags) {
  const root = _tagTree(tags);
  return Object.entries(root.children).map(([n, c]) => _tagNodeHtml(n, c, 0)).join('');
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
let _graphLocal = false;
async function openGraph() {
  $('wiki-graph').style.display = 'flex';
  await fetchGraph();
}
async function fetchGraph() {
  const filt = ($('wiki-graph-filter')?.value || '').trim().replace(/^#/, '');
  let url;
  if (_graphLocal && _cur) {
    const name = _cur.replace(/\.md$/, '').split('/').pop();
    url = `/api/vault-md/local-graph?name=${encodeURIComponent(name)}&depth=2`;
  } else {
    url = filt ? `/api/vault-md/graph?tag=${encodeURIComponent(filt)}` : '/api/vault-md/graph';
  }
  try { renderGraph(await fetch(url).then(r => r.json())); }
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
    const isCenter = data.center && n.id === data.center;
    html += `<g class="wg-node${isCenter ? ' wg-center' : ''}" data-path="${esc(n.path)}"><circle cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="${isCenter ? r + 2 : r}"/><text x="${n.x.toFixed(1)}" y="${(n.y - r - 4).toFixed(1)}">${esc(n.id)}</text></g>`;
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
      // 3q: drop the deleted file (or everything under a deleted folder) from open tabs
      _tabs = _tabs.filter(x => x !== path && !x.startsWith(path + '/'));
      _persistTabs();
      if (_cur && (_cur === path || _cur.startsWith(path + '/'))) _resetEditor();
      renderTabs();
      loadTree();
    }
  }));
}

function _resetEditor() {
  _cur = null; _syncEmpty(); _syncDocUrl();
  setEditor('');
  $('wiki-preview').innerHTML = '';
  $('wiki-backlinks').innerHTML = '';
  const cl = $('wiki-current'); if (cl) cl.textContent = 'no doc open';
}

// keep the open doc in the URL (?doc=path) so refresh / deep-link restores it
function _syncDocUrl() {
  try {
    const u = new URL(location.href);
    if (_cur) u.searchParams.set('doc', _cur); else u.searchParams.delete('doc');
    history.replaceState({}, '', u);
  } catch {}
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
    _syncDocUrl();
    _syncEmpty();
    setEditor(d.content || '');
    const currentLabel = $('wiki-current');
    if (currentLabel) currentLabel.textContent = _cur.replace(/\.md$/, '');
    _addTab(_cur);
    if (_split) renderSplit();
    loadBacklinks();
    loadComments();  // refresh anchors + thread count for this doc (3e)
    document.querySelectorAll('.wiki-file').forEach(f => f.classList.toggle('active', f.dataset.path === _cur));
    if (_docsMode === 'live') { _cm?.view.requestMeasure(); _cm?.focus(); }
    else if (_docsMode === 'source') $('wiki-source')?.focus();
  } catch { toast('failed to open doc', 'error'); }
}

// ── tabs, split (2e) ──────────────────────────────────────────────────────────
function _restoreTabs() {
  try { _tabs = JSON.parse(localStorage.getItem('docs-tabs') || '[]'); } catch { _tabs = []; }
  renderTabs();
}
function _persistTabs() { try { localStorage.setItem('docs-tabs', JSON.stringify(_tabs)); } catch {} }
function _addTab(path) { if (path && !_tabs.includes(path)) { _tabs.push(path); _persistTabs(); } renderTabs(); }
function renderTabs() {
  const el = $('wiki-tabs'); if (!el) return;
  el.innerHTML = _tabs.map(p =>
    `<span class="wiki-tab${p === _cur ? ' active' : ''}" data-path="${esc(p)}"><span class="wiki-tab-name">${esc(p.replace(/\.md$/, '').split('/').pop())}</span><span class="wiki-tab-close" data-close="${esc(p)}">×</span></span>`).join('');
  el.querySelectorAll('.wiki-tab-name').forEach(t => t.addEventListener('click', () => openFile(t.closest('.wiki-tab').dataset.path)));
  el.querySelectorAll('.wiki-tab-close').forEach(c => c.addEventListener('click', e => { e.stopPropagation(); closeTab(c.dataset.close); }));
}
function closeTab(path) {
  _tabs = _tabs.filter(p => p !== path); _persistTabs();
  if (_cur === path) { if (_tabs.length) openFile(_tabs[_tabs.length - 1]); else { _resetEditor(); renderTabs(); } }
  else renderTabs();
}
function toggleSplit() {
  _split = !_split;
  $('wiki-view')?.classList.toggle('split-on', _split);
  $('wiki-split-btn')?.classList.toggle('active', _split);
  if (_split) { openSplitPicker(); } else { _splitDoc = null; }
}
// pick which doc loads on the other side — scope to open tabs or all docs
function openSplitPicker(scope) {
  document.getElementById('split-picker')?.remove();
  scope = scope || 'all';
  const open = _tabs.filter(p => p !== _cur);
  const all = (_homeDocs || []).map(f => f.path).filter(p => p !== _cur);
  const list = scope === 'open' ? open : all;
  const pop = document.createElement('div');
  pop.id = 'split-picker'; pop.className = 'wiki-menu-pop split-picker';
  pop.innerHTML =
    `<div class="sp-scope"><button class="sp-tab${scope === 'open' ? ' on' : ''}" data-s="open">open docs</button>`
    + `<button class="sp-tab${scope === 'all' ? ' on' : ''}" data-s="all">all docs</button></div>`
    + `<div class="sp-list">`
    + (list.length ? list.map(p => `<button class="sp-item" data-p="${esc(p)}">${esc(p.replace(/\.md$/, '').split('/').pop())}</button>`).join('')
      : `<div class="wmp-empty">${scope === 'open' ? 'no other open docs' : 'no other docs'}</div>`)
    + `</div>`;
  document.body.appendChild(pop);
  const btn = $('wiki-split-btn'); const r = btn ? btn.getBoundingClientRect() : { left: 200, bottom: 100 };
  pop.style.left = Math.min(r.left, window.innerWidth - 260) + 'px';
  pop.style.top = (r.bottom + 5) + 'px';
  pop.querySelectorAll('.sp-tab').forEach(t => t.addEventListener('click', () => openSplitPicker(t.dataset.s)));
  pop.querySelectorAll('.sp-item').forEach(b => b.addEventListener('click', () => { _splitDoc = b.dataset.p; pop.remove(); renderSplit(); }));
  setTimeout(() => document.addEventListener('mousedown', function h(ev) { if (!pop.contains(ev.target) && ev.target !== btn) { pop.remove(); document.removeEventListener('mousedown', h); } }), 0);
}
function renderSplit() {
  const pane = $('wiki-split-pane'); if (!pane) return;
  const other = _splitDoc || [..._tabs].reverse().find(p => p !== _cur);
  if (!other) { pane.innerHTML = '<div class="wiki-outline-empty">pick a doc to show side-by-side</div>'; return; }
  fetch(`/api/vault-md/file?path=${encodeURIComponent(other)}`).then(r => r.json()).then(d => {
    pane.innerHTML = `<div class="wiki-split-head">${esc(other.replace(/\.md$/, '').split('/').pop())}<button class="wiki-split-pick" title="change doc">change</button></div><div class="wiki-split-body">${mdToHtml(d.content || '')}</div>`;
    pane.querySelector('.wiki-split-pick')?.addEventListener('click', () => openSplitPicker());
  }).catch(() => {});
}
// draggable divider → set the right pane's width (clamped 20–80%)
function _initSplitDivider() {
  const div = $('wiki-split-divider'); if (!div || div._wired) return; div._wired = true;
  const wrap = div.closest('.wiki-edit-wrap');
  let dragging = false;
  div.addEventListener('pointerdown', e => { dragging = true; div.setPointerCapture(e.pointerId); e.preventDefault(); });
  div.addEventListener('pointermove', e => {
    if (!dragging || !wrap) return;
    const r = wrap.getBoundingClientRect();
    let pct = (r.right - e.clientX) / r.width * 100;   // pane is on the right
    pct = Math.max(20, Math.min(80, pct));
    wrap.style.setProperty('--split', pct + '%');
  });
  const stop = e => { dragging = false; try { div.releasePointerCapture(e.pointerId); } catch {} };
  div.addEventListener('pointerup', stop);
  div.addEventListener('pointercancel', stop);
}

// ── hover preview of a linked note (2a) ───────────────────────────────────────
async function showLinkPreview(a) {
  const name = a.dataset.note;
  let d;
  try { d = await fetch(`/api/vault-md/preview?name=${encodeURIComponent(name)}`).then(r => r.json()); }
  catch { return; }
  if (!d.found) return;
  hideLinkPreview();
  const pop = document.createElement('div');
  pop.className = 'wiki-hoverpop';
  pop.id = 'wiki-hoverpop';
  pop.innerHTML = `<div class="wiki-hoverpop-title">${esc(d.title)}</div><div class="wiki-hoverpop-body">${esc(d.excerpt) || '<em>empty note</em>'}</div>`;
  document.body.appendChild(pop);
  const r = a.getBoundingClientRect();
  pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 340)) + 'px';
  pop.style.top = (r.bottom + 6) + 'px';
}
function hideLinkPreview() { document.getElementById('wiki-hoverpop')?.remove(); }
// small tooltip showing a rendered link's real destination (live mode)
function showUrlTip(a) {
  hideUrlTip();
  const url = a.getAttribute('href') || '';
  if (!url) return;
  const tip = document.createElement('div');
  tip.id = 'wiki-url-tip'; tip.className = 'wiki-url-tip';
  tip.innerHTML = `<span class="wut-url">${esc(url)}</span><span class="wut-hint">${navigator.platform.includes('Mac') ? '⌘' : 'ctrl'}-click to open</span>`;
  document.body.appendChild(tip);
  const r = a.getBoundingClientRect();
  tip.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 340)) + 'px';
  tip.style.top = (r.bottom + 6) + 'px';
}
function hideUrlTip() { document.getElementById('wiki-url-tip')?.remove(); }

// ── bookmarks (2a) ────────────────────────────────────────────────────────────
async function _loadBookmarks() {
  try { _bookmarks = (await fetch('/api/vault-md/bookmarks').then(r => r.json())).bookmarks || []; }
  catch { _bookmarks = []; }
}
function _isBookmarked(path) { return _bookmarks.some(b => b.path === path); }
// bookmark a doc by path (3k: callable from the home doc cards, no open doc needed)
async function _bookmarkPath(path) {
  if (!path) return;
  try {
    const r = await fetch('/api/vault-md/bookmarks', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ path, title: path.replace(/\.md$/, '').split('/').pop() }),
    }).then(r => r.json());
    _bookmarks = r.bookmarks || [];
    toast(r.bookmarked ? 'bookmarked' : 'bookmark removed', '');
  } catch { toast('failed', 'error'); }
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
  // live embeds (3b): a standalone allow-listed URL line, or ![embed](url) → iframe.
  // stash as a token before markdown so it isn't mangled, restore after.
  const _embeds = [];
  const _stash = url => { _embeds.push(url); return `%%LIVEEMBED${_embeds.length - 1}%%`; };
  src = src.replace(/^!\[embed\]\((https?:\/\/[^\s)]+)\)\s*$/gim, (_, u) => _stash(u));
  src = src.replace(/^(https?:\/\/(?:www\.)?(?:youtube\.com|youtu\.be|open(?:street)?map\.org|twitter\.com|x\.com)\/[^\s]+)\s*$/gim, (_, u) => _stash(u));
  let html = mdToHtml(src);
  html = html.replace(/%%LIVEEMBED(\d+)%%/g, (_, i) => _liveEmbed(_embeds[+i]));
  // synced blocks (3b): ![[note#^id]] mirrors a block — must run before the whole-note embed
  html = html.replace(/!\[\[([^\]#|]+)#\^([A-Za-z0-9_-]+)\]\]/g, (_, note, id) =>
    `<div class="md-syncblock" data-note="${esc(note.trim())}" data-block="${esc(id)}"><span class="md-embed-loading">…</span></div>`);
  html = html.replace(/!\[\[([^\]|#]+?)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]/g, (_, name, alias) => embedHtml(name.trim(), alias));
  html = html.replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]/g, (_, name, alias) => `<a class="wikilink" data-note="${esc(name.trim())}">${esc((alias || name).trim())}</a>`);
  html = html.replace(/(^|[\s(>])#([A-Za-z0-9][A-Za-z0-9_/\-]*)/g, (_, pre, tag) => `${pre}<span class="md-tag" data-tag="${esc(tag)}">#${esc(tag)}</span>`);
  // @date mentions (3a) — @today / @tomorrow / @YYYY-MM-DD
  html = html.replace(/(^|[\s(>])@(today|tomorrow|\d{4}-\d{2}-\d{2})\b/g, (_, pre, d) => `${pre}<span class="md-datemention">📅 ${esc(d)}</span>`);
  // template buttons (3c): %%button: Name%% → inserts the named template
  html = html.replace(/%%button:\s*([^%]+?)\s*%%/g, (_, name) => `<button class="md-tmpl-btn" data-tmpl="${esc(name.trim())}">+ ${esc(name.trim())}</button>`);
  $('wiki-preview').innerHTML = fmHtml + html;
  $('wiki-preview').querySelectorAll('.md-tmpl-btn').forEach(btn => btn.addEventListener('click', () => insertTemplateByName(btn.dataset.tmpl)));
  enhanceMarkdown($('wiki-preview'));
  fillEmbeds();
  fillSyncBlocks();
  fillQueryBlocks();
  fillFormBlocks();
  _applyCommentMarks();
  if ($('wiki-outline') && $('wiki-outline').style.display !== 'none') updateOutline();
}

// allow-listed live embeds → sandboxed iframe (3b)
function _liveEmbed(url) {
  let src = '';
  let m;
  if ((m = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([\w-]+)/))) src = `https://www.youtube.com/embed/${m[1]}`;
  else if (/open(?:street)?map\.org/.test(url)) {
    src = url.replace('/#map=', '/export/embed.html?#map=');
    if (!src.includes('embed')) src = 'https://www.openstreetmap.org/export/embed.html';
  } else if (/twitter\.com|x\.com/.test(url)) {
    return `<blockquote class="md-embed-tweet"><a href="${esc(url)}" target="_blank" rel="noopener">view tweet ↗</a></blockquote>`;
  } else src = url;
  return `<div class="md-live-embed"><iframe src="${esc(src)}" loading="lazy" sandbox="allow-scripts allow-same-origin allow-popups" referrerpolicy="no-referrer" allowfullscreen></iframe></div>`;
}

async function insertTemplateByName(name) {
  try {
    const d = await fetch('/api/vault-md/templates').then(r => r.json());
    const t = (d.templates || []).find(x => x.name.toLowerCase() === name.toLowerCase());
    if (!t) { toast('template not found', 'error'); return; }
    setEditor(getEditor() + '\n' + t.content);
    queueSave();
    toast('inserted ' + name, '');
  } catch { toast('insert failed', 'error'); }
}

function fillSyncBlocks() {
  $('wiki-preview')?.querySelectorAll('.md-syncblock[data-note]').forEach(async el => {
    const note = el.dataset.note, id = el.dataset.block;
    try {
      const d = await fetch(`/api/vault-md/block?path=${encodeURIComponent(note)}&id=${encodeURIComponent(id)}`).then(r => r.json());
      el.innerHTML = d.found
        ? `<div class="md-syncblock-body">${mdToHtml(d.text)}</div><div class="md-syncblock-src">↔ synced from ${esc(note)}</div>`
        : `<div class="md-embed-loading">block ^${esc(id)} not found in ${esc(note)}</div>`;
    } catch { el.innerHTML = '<div class="md-embed-loading">could not load block</div>'; }
  });
}

// render inline ```query / ```dataview fences as live tables (2b)
async function fillQueryBlocks() {
  const blocks = $('wiki-preview')?.querySelectorAll('code.language-query, code.language-dataview');
  if (!blocks || !blocks.length) return;
  for (const code of blocks) {
    const pre = code.closest('pre') || code;
    const spec = code.textContent || '';
    let d;
    try {
      d = await fetch('/api/vault-md/query-block', {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ spec }),
      }).then(r => r.json());
    } catch { continue; }
    const wrap = document.createElement('div');
    wrap.className = 'wiki-queryblock';
    wrap.innerHTML = _renderQueryResult(d);
    pre.replaceWith(wrap);
    wrap.querySelectorAll('.wikilink').forEach(a =>
      a.addEventListener('click', e => { e.preventDefault(); openByName(a.dataset.note); }));
  }
}
// render ```form fences as a fillable form that appends a row to the target note (3d)
function fillFormBlocks() {
  const blocks = $('wiki-preview')?.querySelectorAll('code.language-form');
  if (!blocks || !blocks.length) return;
  for (const code of blocks) {
    const pre = code.closest('pre') || code;
    const spec = {};
    for (const line of (code.textContent || '').split('\n')) {
      const m = line.match(/^\s*([A-Za-z0-9_]+)\s*:\s*(.+)$/);
      if (m) spec[m[1].toLowerCase()] = m[2].trim();
    }
    const target = spec.target || '';
    const fields = (spec.fields || '').split(',').map(s => s.trim()).filter(Boolean);
    const wrap = document.createElement('form');
    wrap.className = 'wiki-form';
    if (!target || !fields.length) {
      wrap.innerHTML = '<div class="wiki-outline-empty">form needs `target:` and `fields:`</div>';
      pre.replaceWith(wrap);
      continue;
    }
    wrap.innerHTML = fields.map(f =>
      `<label class="wiki-form-field"><span>${esc(f)}</span><input name="${esc(f)}" class="settings-input" autocomplete="off"></label>`).join('') +
      `<button type="submit" class="btn primary wiki-form-submit">submit</button><span class="wiki-form-msg"></span>`;
    wrap.addEventListener('submit', async e => {
      e.preventDefault();
      const values = {};
      fields.forEach(f => { values[f] = wrap.querySelector(`[name="${CSS.escape(f)}"]`)?.value || ''; });
      const msg = wrap.querySelector('.wiki-form-msg');
      try {
        const d = await fetch('/api/vault-md/form-submit', {
          method: 'POST', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ target, fields, values }),
        }).then(r => r.json());
        if (msg) msg.textContent = d.ok ? `saved (row ${d.count})` : 'failed';
        fields.forEach(f => { const i = wrap.querySelector(`[name="${CSS.escape(f)}"]`); if (i) i.value = ''; });
      } catch { if (msg) msg.textContent = 'failed'; }
    });
    pre.replaceWith(wrap);
  }
}
function _renderQueryResult(d) {
  const link = r => `<a class="wikilink" data-note="${esc(r.name)}">${esc(r.name)}</a>`;
  const head = `<div class="wiki-qb-head">${d.count} result${d.count === 1 ? '' : 's'}${d.group ? ` · grouped by ${esc(d.group)}` : ''}</div>`;
  if (d.group && d.groups) {
    const chart = d.chart ? _renderChart(d.chart, d.groups) : '';
    return head + chart + d.groups.map(g =>
      `<div class="wiki-qb-group"><div class="wiki-qb-gkey">${esc(g.key)} <span class="wiki-qb-gcount">${g.count != null ? g.count : g.rows.length}</span></div>${g.rows.map(link).join(' · ')}</div>`).join('');
  }
  if (!d.rows || !d.rows.length) return '<div class="wiki-qb-head">no results</div>';
  return head + '<ul class="wiki-qb-list">' + d.rows.map(r => `<li>${link(r)}</li>`).join('') + '</ul>';
}
// inline svg chart over grouped query results (3d). type = bar | pie | line.
function _renderChart(type, groups) {
  const data = (groups || []).map(g => ({ k: String(g.key), v: g.count != null ? g.count : (g.rows || []).length }));
  if (!data.length) return '';
  const max = Math.max(1, ...data.map(d => d.v));
  const palette = ['#818cf8', '#4ade80', '#f87171', '#fbbf24', '#22d3ee', '#c084fc', '#fb923c', '#34d399'];
  const W = 360, H = 160;
  if (type === 'pie') {
    const total = data.reduce((s, d) => s + d.v, 0) || 1;
    let a0 = -Math.PI / 2;
    const R = 60, cx = 80, cy = 80;
    const slices = data.map((d, i) => {
      const a1 = a0 + (d.v / total) * Math.PI * 2;
      const x0 = cx + R * Math.cos(a0), y0 = cy + R * Math.sin(a0);
      const x1 = cx + R * Math.cos(a1), y1 = cy + R * Math.sin(a1);
      const large = (a1 - a0) > Math.PI ? 1 : 0;
      a0 = a1;
      return `<path d="M${cx},${cy} L${x0.toFixed(1)},${y0.toFixed(1)} A${R},${R} 0 ${large} 1 ${x1.toFixed(1)},${y1.toFixed(1)} Z" fill="${palette[i % palette.length]}"></path>`;
    }).join('');
    const legend = data.map((d, i) => `<div class="wiki-chart-leg"><span style="background:${palette[i % palette.length]}"></span>${esc(d.k)} (${d.v})</div>`).join('');
    return `<div class="wiki-chart"><svg viewBox="0 0 160 160" width="160" height="160">${slices}</svg><div class="wiki-chart-legend">${legend}</div></div>`;
  }
  if (type === 'line') {
    const step = data.length > 1 ? (W - 40) / (data.length - 1) : 0;
    const pts = data.map((d, i) => `${(20 + i * step).toFixed(1)},${(H - 20 - (d.v / max) * (H - 40)).toFixed(1)}`);
    const dots = pts.map((p, i) => { const [x, y] = p.split(','); return `<circle cx="${x}" cy="${y}" r="3" fill="#818cf8"></circle><text x="${x}" y="${H - 4}" font-size="9" fill="#6e6e6e" text-anchor="middle">${esc(data[i].k.slice(0, 6))}</text>`; }).join('');
    return `<div class="wiki-chart"><svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}"><polyline points="${pts.join(' ')}" fill="none" stroke="#818cf8" stroke-width="2"></polyline>${dots}</svg></div>`;
  }
  // bar (default)
  const bw = Math.min(48, (W - 40) / data.length - 8);
  const bars = data.map((d, i) => {
    const x = 20 + i * ((W - 40) / data.length);
    const h = (d.v / max) * (H - 40);
    const y = H - 20 - h;
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" fill="${palette[i % palette.length]}"></rect>` +
      `<text x="${(x + bw / 2).toFixed(1)}" y="${(y - 3).toFixed(1)}" font-size="9" fill="#e8e6e3" text-anchor="middle">${d.v}</text>` +
      `<text x="${(x + bw / 2).toFixed(1)}" y="${H - 4}" font-size="9" fill="#6e6e6e" text-anchor="middle">${esc(d.k.slice(0, 8))}</text>`;
  }).join('');
  return `<div class="wiki-chart"><svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}">${bars}</svg></div>`;
}
function renderFrontmatter(raw) {
  const rows = [];
  for (const line of raw.split('\n')) { const m = line.match(/^([A-Za-z0-9_][\w \-]*):\s*(.*)$/); if (m) rows.push([m[1].trim(), m[2].trim()]); }
  if (!rows.length) return '';
  // page cover + icon/emoji banner (3a)
  const get = k => (rows.find(r => r[0].toLowerCase() === k) || [])[1] || '';
  const cover = get('cover'), icon = get('icon');
  let banner = '';
  if (cover) {
    const src = /^https?:\/\//.test(cover) ? cover : `/api/vault-md/raw?path=${encodeURIComponent(cover)}`;
    banner += `<div class="md-cover" style="background-image:url('${esc(src)}')"></div>`;
  }
  if (icon) banner += `<div class="md-page-icon">${esc(icon)}</div>`;
  const shown = rows.filter(r => !['cover', 'icon'].includes(r[0].toLowerCase()));
  const fm = shown.length
    ? `<div class="md-frontmatter">` + shown.map(([k, v]) => `<div class="md-fm-row"><span class="md-fm-key">${esc(k)}</span><span class="md-fm-val">${esc(v || '—')}</span></div>`).join('') + `</div>`
    : '';
  return banner + fm;
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

// 3s: explain what AI todo-extraction does before running it (like the other panels)
function openTodosExplainer(btn) {
  const already = document.getElementById('wiki-todos-pop');
  // re-clicking the todos button closes the popup (real toggle, like the side panels)
  if (already) { already.remove(); btn.classList.remove('active'); return; }
  if (!_cur) { toast('open a doc first', 'error'); return; }
  _closeOtherPanels('wiki-todos');            // opening todos closes any open side panel
  btn.classList.add('active');                // and lights its own indicator
  const pop = document.createElement('div');
  pop.id = 'wiki-todos-pop'; pop.className = 'wiki-menu-pop wiki-explainer-pop';
  pop.innerHTML = `<div class="wep-title">extract to-dos with AI</div>
    <div class="wep-body">scans this doc for action items — checkboxes, “TODO”, and anything that reads like a task — and creates real tasks from them in the <b>tasks</b> app. The doc isn’t changed.</div>
    <button class="wmp-item wep-go" id="wiki-todos-go">extract to-dos</button>`;
  document.body.appendChild(pop);
  const r = btn.getBoundingClientRect();
  pop.style.left = Math.min(r.left, window.innerWidth - 280) + 'px';
  pop.style.top = (r.bottom + 5) + 'px';
  const close = () => { pop.remove(); btn.classList.remove('active'); };
  pop.querySelector('#wiki-todos-go').addEventListener('click', () => { close(); _runExtractTodos(); });
  setTimeout(() => document.addEventListener('mousedown', function h(ev) { if (!pop.contains(ev.target) && ev.target !== btn) { close(); document.removeEventListener('mousedown', h); } }), 0);
}
async function _runExtractTodos() {
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

function toggleHistory() { _togglePanel('wiki-history', 'wiki-history-btn', loadHistory); }
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
  panel.innerHTML = '<div class="wiki-rev-label">version history</div>' + revs.map(r => `
    <div class="wiki-rev" data-rev="${r.id}">
      <div class="wiki-rev-row">
        <span class="wiki-rev-when">${_revAgo(r.created_at)}</span>
        <span class="wiki-rev-size">${(r.size / 1000).toFixed(1)}k</span>
        <button class="btn wiki-rev-btn" data-rev-diff="${r.id}">diff</button>
        <button class="btn wiki-rev-btn" data-rev-restore="${r.id}">restore</button>
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
  return `<pre class="wiki-rev-diff-pre">${body}</pre>`;
}

// side panels are an accordion — opening one closes the rest so you never get
// multiple "active" (glowing) buttons for panels that aren't actually shown.
const _SIDE_PANELS = [
  ['wiki-outline', 'wiki-outline-btn'],
  ['wiki-props', 'wiki-props-btn'],
  ['wiki-query', 'wiki-query-btn'],
  ['wiki-ask', 'wiki-ask-btn'],
  ['wiki-history', 'wiki-history-btn'],
  ['wiki-comments', 'wiki-comments-btn'],
  ['wiki-base', 'wiki-base-btn'],
  ['wiki-taskroll', 'wiki-taskroll-btn'],
];
function _closeOtherPanels(keep) {
  for (const [panel, btn] of _SIDE_PANELS) {
    if (panel === keep) continue;
    const p = $(panel); if (p) p.style.display = 'none';
    $(btn)?.classList.remove('active');
  }
  // the todos explainer is a popup, not a side panel — close it + drop its indicator too
  if (keep !== 'wiki-todos') {
    document.getElementById('wiki-todos-pop')?.remove();
    $('wiki-todos-btn')?.classList.remove('active');
  }
}

// one toggle for every docs side panel: opening one closes the rest, the button glows while open
function _togglePanel(panelId, btnId, onShow) {
  const p = $(panelId); if (!p) return;
  const show = p.style.display === 'none' || !p.style.display;
  _closeOtherPanels(panelId);
  p.style.display = show ? 'block' : 'none';
  $(btnId)?.classList.toggle('active', show);
  if (show && onShow) onShow();
}

function toggleOutline() { _togglePanel('wiki-outline', 'wiki-outline-btn', updateOutline); }
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
  if (!heads.length) { panel.innerHTML = '<div class="wiki-outline-head">outline</div><div class="wiki-outline-empty">no headings yet — start a line with <code>#</code> (or <code>##</code>, <code>###</code>…) and it shows up here as a jump-to link</div>'; return; }
  panel.innerHTML = `<div class="wiki-outline-head">outline · ${heads.length} heading${heads.length !== 1 ? 's' : ''}</div>` + heads.map(h =>
    `<div class="wiki-outline-item lvl${h.level}" data-line="${h.line}" style="padding-left:${0.7 + (h.level - 1) * 0.85}rem">${esc(h.text)}</div>`).join('');
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
function toggleProps() { _togglePanel('wiki-props', 'wiki-props-btn', loadProps); }
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

// ── slash "/" insert menu (live CM6 + source textarea) ───────────────────────
let _slashOpen = false, _slashItems = [], _slashSel = 0, _slashCtx = null;
function _editorCtx() {
  if (_docsMode === 'source') {
    const ta = $('wiki-source'); if (!ta) return null;
    return { mode: 'source', text: ta.value, pos: ta.selectionStart, el: ta };
  }
  if (_docsMode === 'live' && _cm?.view) {
    const v = _cm.view; const head = v.state.selection.main.head;
    return { mode: 'live', text: v.state.doc.toString(), pos: head, view: v };
  }
  return null;
}
async function slashDetect() {
  const ctx = _editorCtx(); if (!ctx) return hideSlash();
  const { text, pos } = ctx;
  let i = pos - 1;
  while (i >= 0 && !/\s/.test(text[i]) && text[i] !== '/') i--;
  if (i < 0 || text[i] !== '/') return hideSlash();
  const before = i > 0 ? text[i - 1] : '\n';
  if (i !== 0 && !/\s/.test(before)) return hideSlash();   // mid-word slash (e.g. a/b) — ignore
  const q = text.slice(i + 1, pos);
  if (/\s/.test(q)) return hideSlash();
  _slashCtx = { ...ctx, start: i, end: pos };
  let cmds = [];
  try { cmds = (await fetch(`/api/vault-md/slash-commands?q=${encodeURIComponent(q)}`).then(r => r.json())).commands || []; }
  catch { return hideSlash(); }
  if (!cmds.length) return hideSlash();
  _slashItems = cmds; _slashSel = 0;
  renderSlash();
}
function _caretCoords(ctx) {
  if (ctx.mode === 'live') {
    const c = ctx.view.coordsAtPos(ctx.end);
    return c ? { left: c.left, top: c.bottom } : null;
  }
  // textarea: mirror div to find the caret pixel
  const ta = ctx.el, r = ta.getBoundingClientRect();
  const div = document.createElement('div'); const s = getComputedStyle(ta);
  for (const pr of ['fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'paddingTop', 'paddingLeft', 'paddingRight', 'whiteSpace', 'wordWrap', 'letterSpacing']) div.style[pr] = s[pr];
  div.style.position = 'absolute'; div.style.visibility = 'hidden'; div.style.whiteSpace = 'pre-wrap'; div.style.wordWrap = 'break-word';
  div.style.width = ta.clientWidth + 'px';
  div.textContent = ta.value.slice(0, _slashCtx.end);
  const span = document.createElement('span'); span.textContent = '​'; div.appendChild(span);
  document.body.appendChild(div);
  const top = r.top + (span.offsetTop - ta.scrollTop) + 18;
  const left = r.left + (span.offsetLeft);
  div.remove();
  return { left, top };
}
function renderSlash() {
  const box = $('wiki-slash'); if (!box) return;
  box.innerHTML = _slashItems.map((c, i) =>
    `<div class="wiki-slash-item${i === _slashSel ? ' active' : ''}" data-i="${i}"><span class="wiki-slash-label">${esc(c.label)}</span><span class="wiki-slash-id">/${esc(c.id)}</span></div>`).join('');
  const co = _caretCoords(_slashCtx);
  if (co) { box.style.left = Math.min(co.left, window.innerWidth - 230) + 'px'; box.style.top = co.top + 'px'; }
  box.style.display = 'block';
  _slashOpen = true;
  box.querySelectorAll('.wiki-slash-item').forEach(el => el.addEventListener('mousedown', e => { e.preventDefault(); pickSlash(+el.dataset.i); }));
}
function hideSlash() { const b = $('wiki-slash'); if (b) b.style.display = 'none'; _slashOpen = false; _slashItems = []; }
function pickSlash(i) {
  const cmd = _slashItems[i]; if (!cmd || !_slashCtx) return hideSlash();
  let snip = cmd.snippet, caret;
  const ci = snip.indexOf('{}');
  if (ci >= 0) { snip = snip.replace('{}', ''); caret = _slashCtx.start + ci; } else caret = _slashCtx.start + snip.length;
  if (_slashCtx.mode === 'live') {
    _slashCtx.view.dispatch({ changes: { from: _slashCtx.start, to: _slashCtx.end, insert: snip }, selection: { anchor: caret } });
    _slashCtx.view.focus();
  } else {
    const ta = _slashCtx.el, v = ta.value;
    ta.value = v.slice(0, _slashCtx.start) + snip + v.slice(_slashCtx.end);
    ta.setSelectionRange(caret, caret); ta.focus(); onSourceInput();
  }
  hideSlash();
}
function _slashKeydown(e) {
  if (!_slashOpen || !_slashItems.length) return;
  if (e.key === 'ArrowDown') { e.preventDefault(); e.stopPropagation(); _slashSel = (_slashSel + 1) % _slashItems.length; renderSlash(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); _slashSel = (_slashSel - 1 + _slashItems.length) % _slashItems.length; renderSlash(); }
  else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); pickSlash(_slashSel); }
  else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); hideSlash(); }
}

// ── kanban board (over the current doc) ──────────────────────────────────────
let _boardCardDrag = null;  // { line, fromCol }
async function openBoard() {
  if (!_cur) { toast('open a doc first', 'error'); return; }
  await flushSave();
  $('wiki-board').style.display = 'flex';
  $('wiki-board-title').textContent = `board · ${_cur.replace(/\.md$/, '')}`;
  await loadBoard();
}
async function loadBoard() {
  const wrap = $('wiki-board-cols'); if (!wrap) return;
  let cols = [];
  try { cols = (await fetch(`/api/vault-md/board?path=${encodeURIComponent(_cur)}`).then(r => r.json())).columns || []; }
  catch { wrap.innerHTML = '<div class="wiki-outline-empty">failed to load board</div>'; return; }
  if (!cols.length) { wrap.innerHTML = '<div class="wiki-board-empty">no columns — add a <code>## Heading</code> with <code>- [ ] cards</code> to this doc, or click “+ column”.</div><button class="btn" id="wiki-board-newcol">+ column</button>'; $('wiki-board-newcol')?.addEventListener('click', addColumn); return; }
  wrap.innerHTML = cols.map(c => `
    <div class="wiki-board-col" data-col="${esc(c.name)}">
      <div class="wiki-board-colhead">${esc(c.name)} <span class="wiki-board-count">${c.cards.length}</span></div>
      <div class="wiki-board-cards" data-col="${esc(c.name)}">
        ${c.cards.map(card => `<div class="wiki-board-card${card.done ? ' done' : ''}" draggable="true" data-line="${card.line}" data-col="${esc(c.name)}">
          <span class="wiki-board-chk" data-toggle aria-checked="${card.done}"></span><span class="wiki-board-text">${esc(card.text)}</span></div>`).join('')}
      </div>
      <button class="wiki-board-add" data-col="${esc(c.name)}">+ card</button>
    </div>`).join('') + `<button class="btn wiki-board-newcol-btn" id="wiki-board-newcol">+ column</button>`;
  wireBoard();
}
function wireBoard() {
  const wrap = $('wiki-board-cols');
  wrap.querySelectorAll('.wiki-board-card').forEach(card => {
    card.addEventListener('dragstart', () => { _boardCardDrag = { line: +card.dataset.line, fromCol: card.dataset.col }; card.classList.add('dragging'); });
    card.addEventListener('dragend', () => { card.classList.remove('dragging'); _boardCardDrag = null; });
    card.querySelector('[data-toggle]')?.addEventListener('click', async e => {
      e.stopPropagation();
      const done = card.querySelector('[data-toggle]').getAttribute('aria-checked') !== 'true';
      await fetch('/api/vault-md/task', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: _cur, line: +card.dataset.line, done }) });
      await loadBoard(); await reloadCurrentDoc();
    });
  });
  wrap.querySelectorAll('.wiki-board-cards').forEach(zone => {
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drop'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drop'));
    zone.addEventListener('drop', async e => {
      e.preventDefault(); zone.classList.remove('drop');
      if (!_boardCardDrag) return;
      const toCol = zone.dataset.col;
      if (toCol === _boardCardDrag.fromCol) return;
      await fetch('/api/vault-md/board/move', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: _cur, line: _boardCardDrag.line, to_col: toCol }) });
      await loadBoard(); await reloadCurrentDoc();
    });
  });
  wrap.querySelectorAll('.wiki-board-add').forEach(btn => btn.addEventListener('click', async () => {
    const text = await dlgPrompt(`new card in “${btn.dataset.col}”:`);
    if (!text?.trim()) return;
    await fetch('/api/vault-md/board/add', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: _cur, column: btn.dataset.col, text: text.trim() }) });
    await loadBoard(); await reloadCurrentDoc();
  }));
  $('wiki-board-newcol')?.addEventListener('click', addColumn);
}
async function addColumn() {
  const name = await dlgPrompt('column name:');
  if (!name?.trim()) return;
  const text = await dlgPrompt('first card (optional):');
  await fetch('/api/vault-md/board/add', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: _cur, column: name.trim(), text: (text || 'new card').trim() }) });
  await loadBoard(); await reloadCurrentDoc();
}
async function reloadCurrentDoc() {
  if (!_cur) return;
  const d = await fetch(`/api/vault-md/file?path=${encodeURIComponent(_cur)}`).then(r => r.json());
  setEditor(d.content || '');
}

// ── note query (dataview-lite) ───────────────────────────────────────────────
const _QOPS = ['eq', 'ne', 'contains', 'gt', 'lt', 'exists', 'missing'];
let _qFilters = [{ field: 'status', op: 'eq', value: '' }];
let _qSort = { field: '', dir: 'asc' };
// ── Bases: a folder as a database (2c) ────────────────────────────────────────
let _baseView = 'table';
let _baseData = null;
let _baseFolder = '';
function toggleBase() { _togglePanel('wiki-base', 'wiki-base-btn', openBase); }
async function openBase() {
  _baseFolder = _cur && _cur.includes('/') ? _cur.slice(0, _cur.lastIndexOf('/')) : '';
  try { _baseData = await fetch(`/api/vault-md/base?folder=${encodeURIComponent(_baseFolder)}`).then(r => r.json()); }
  catch { _baseData = { columns: [], rows: [] }; }
  renderBase();
}
function renderBase() {
  const p = $('wiki-base'); if (!p || !_baseData) return;
  const views = ['table', 'gallery', 'list'];
  const sw = `<div class="wiki-base-head"><span class="wiki-base-folder">${esc(_baseFolder || '(root)')}</span>`
    + `<span class="wiki-base-views">${views.map(v => `<button class="wiki-base-vbtn${v === _baseView ? ' active' : ''}" data-v="${v}">${v}</button>`).join('')}`
    + `<button class="wiki-base-vbtn" id="wiki-base-newrow" title="add a new note (row) to this folder">+ row</button>`
    + `<button class="wiki-base-vbtn" id="wiki-base-publish" title="publish this folder as a site">publish site</button></span></div>`;
  const rows = _baseData.rows || [], cols = _baseData.columns || [];
  let body = '';
  if (!rows.length) body = '<div class="wiki-outline-empty">no notes in this folder</div>';
  else if (_baseView === 'list') {
    body = '<ul class="wiki-base-list">' + rows.map(r => `<li class="wiki-base-open" data-path="${esc(r.path)}">${esc(r.name)}</li>`).join('') + '</ul>';
  } else if (_baseView === 'gallery') {
    body = '<div class="wiki-base-gallery">' + rows.map(r =>
      `<div class="wiki-base-card wiki-base-open" data-path="${esc(r.path)}"><div class="wiki-base-card-title">${esc(r.name)}</div>`
      + cols.slice(0, 3).map(c => `<div class="wiki-base-card-prop">${esc(c)}: ${esc(_cellVal(r.props[c]))}</div>`).join('') + '</div>').join('') + '</div>';
  } else {
    body = '<table class="wiki-base-table"><thead><tr><th>name</th>' + cols.map(c => `<th>${esc(c)}</th>`).join('') + '</tr></thead><tbody>'
      + rows.map(r => `<tr><td class="wiki-base-open" data-path="${esc(r.path)}">${esc(r.name)}</td>`
        + cols.map(c => `<td class="wiki-base-cell" data-path="${esc(r.path)}" data-key="${esc(c)}">${esc(_cellVal(r.props[c]))}</td>`).join('') + '</tr>').join('')
      + '</tbody></table>';
  }
  p.innerHTML = sw + body;
  p.querySelectorAll('.wiki-base-vbtn[data-v]').forEach(b => b.addEventListener('click', () => { _baseView = b.dataset.v; renderBase(); }));
  $('wiki-base-newrow')?.addEventListener('click', baseNewRow);
  $('wiki-base-publish')?.addEventListener('click', basePublish);
  p.querySelectorAll('.wiki-base-open').forEach(el => el.addEventListener('click', () => openFile(el.dataset.path)));
  p.querySelectorAll('.wiki-base-cell').forEach(td => td.addEventListener('click', () => editBaseCell(td)));
}
function _cellVal(v) { return Array.isArray(v) ? v.join(', ') : (v == null ? '' : String(v)); }
async function baseNewRow() {
  const name = await dlgPrompt('new note name:');
  if (!name) return;
  const cols = (_baseData && _baseData.columns) || [];
  const fm = cols.length ? '---\n' + cols.map(c => `${c}: `).join('\n') + '\n---\n' : '';
  const path = (_baseFolder ? _baseFolder + '/' : '') + name.replace(/\.md$/, '');
  try {
    await fetch('/api/vault-md/file', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path, content: fm }) });
    toast('row added', '');
    openBase();
  } catch { toast('failed', 'error'); }
}
async function basePublish() {
  try {
    const d = await fetch('/api/vault-md/publish-folder', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ folder: _baseFolder }) }).then(r => r.json());
    const idx = (d.published || [])[0];
    if (idx) { try { await navigator.clipboard.writeText(location.origin + idx.url); } catch {} }
    toast(`published ${d.count} page(s) — link copied`, '');
  } catch { toast('publish failed', 'error'); }
}
function editBaseCell(td) {
  if (td.querySelector('input')) return;
  const path = td.dataset.path, key = td.dataset.key, old = td.textContent;
  td.innerHTML = `<input class="wiki-base-input" value="${esc(old)}">`;
  const inp = td.querySelector('input'); inp.focus(); inp.select();
  const save = async () => {
    const val = inp.value;
    try {
      await fetch('/api/vault-md/base-cell', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path, key, value: val }) });
      const row = (_baseData.rows || []).find(r => r.path === path);
      if (row) { if (val === '') delete row.props[key]; else row.props[key] = val; }
      td.textContent = val;
    } catch { td.textContent = old; toast('cell save failed', 'error'); }
  };
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); inp.blur(); } if (e.key === 'Escape') { td.textContent = old; } });
  inp.addEventListener('blur', save);
}

function toggleQuery() {
  const p = $('wiki-query'); if (!p) return;
  const show = p.style.display === 'none' || !p.style.display;
  _closeOtherPanels('wiki-query');
  p.style.display = show ? 'block' : 'none';
  $('wiki-query-btn')?.classList.toggle('active', show);
  if (show) renderQuery();
}

// ask-anything across the whole vault (3d) — retrieval over the 1c text index
function toggleAsk() {
  _togglePanel('wiki-ask', 'wiki-ask-btn', () => { _loadClipBookmarklet(); $('wiki-ask-input')?.focus(); });
}
async function runAsk() {
  const q = ($('wiki-ask-input')?.value || '').trim();
  const out = $('wiki-ask-results'); if (!out) return;
  if (!q) { out.innerHTML = '<div class="wiki-outline-empty">type a question</div>'; return; }
  out.innerHTML = '<div class="wiki-outline-empty">searching…</div>';
  let d;
  try { d = await fetch(`/api/vault-md/ask?q=${encodeURIComponent(q)}`).then(r => r.json()); }
  catch { out.innerHTML = '<div class="wiki-outline-empty">search failed</div>'; return; }
  const hits = d.sources || [];
  if (!hits.length) { out.innerHTML = '<div class="wiki-outline-empty">no matching notes</div>'; return; }
  out.innerHTML = `<div class="wiki-qb-head">${hits.length} source${hits.length === 1 ? '' : 's'}</div>` +
    hits.map(h => {
      const ref = h.ref || '';
      const snip = (h.chunk || '').replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '').trim().slice(0, 220);
      return `<div class="wiki-ask-hit" data-path="${esc(ref)}"><div class="wiki-ask-hit-name">${esc(ref)}</div><div class="wiki-ask-hit-snip">${esc(snip)}</div></div>`;
    }).join('');
  out.querySelectorAll('.wiki-ask-hit[data-path]').forEach(el =>
    el.addEventListener('click', () => openFile(el.dataset.path)));
}
async function _loadClipBookmarklet() {
  const a = $('wiki-clip-bm'); if (!a || a.dataset.ready) return;
  try {
    const d = await fetch('/api/vault-md/clipper-bookmarklet').then(r => r.json());
    a.setAttribute('href', d.bookmarklet || '#');
    a.dataset.ready = '1';
  } catch {}
}

// ── inline comments (3e) ──────────────────────────────────────────────────────
let _commentThreads = [];
let _commentAnchors = [];
let _selText = '';

function toggleComments() { _togglePanel('wiki-comments', 'wiki-comments-btn', loadComments); }
async function loadComments() {
  const p = $('wiki-comments');
  if (!_cur) { _commentThreads = []; _commentAnchors = []; if (p) p.innerHTML = '<div class="wiki-outline-empty">open a doc first</div>'; _updateCommentCount(); return; }
  try { _commentThreads = (await fetch(`/api/vault-md/comments?path=${encodeURIComponent(_cur)}`).then(r => r.json())).threads || []; }
  catch { return; }
  _commentAnchors = _commentThreads.filter(t => !t.resolved && t.anchor && !t.orphaned).map(t => t.anchor);
  renderComments();
  _applyCommentMarks();
  _updateCommentCount();
}
function _updateCommentCount() {
  const el = $('wiki-comments-count'); if (!el) return;
  const open = _commentThreads.filter(t => !t.resolved).length;
  el.textContent = open ? String(open) : '';
}
function renderComments() {
  const p = $('wiki-comments'); if (!p) return;
  if (!_commentThreads.length) { p.innerHTML = '<div class="wiki-outline-empty">no comments yet — select any text in the editor and click the “comment” chip to start a thread</div>'; return; }
  p.innerHTML = _commentThreads.map(t => {
    const replies = (t.replies || []).map(r =>
      `<div class="wiki-cmt-reply"><span class="wiki-cmt-author">${esc(r.author)}</span> ${esc(r.body)}</div>`).join('');
    const anchor = t.anchor
      ? `<div class="wiki-cmt-anchor${t.orphaned ? ' orphaned' : ''}">“${esc(t.anchor.slice(0, 80))}”${t.orphaned ? ' <span class="wiki-cmt-orphan">(orphaned)</span>' : ''}</div>`
      : '';
    return `<div class="wiki-cmt-thread${t.resolved ? ' resolved' : ''}" data-id="${esc(t.id)}">
      ${anchor}
      <div class="wiki-cmt-body"><span class="wiki-cmt-author">${esc(t.author)}</span> ${esc(t.body)}</div>
      ${replies}
      <div class="wiki-cmt-actions">
        <input class="settings-input wiki-cmt-reply-input" placeholder="reply…" data-id="${esc(t.id)}">
        <button class="btn wiki-cmt-resolve" data-id="${esc(t.id)}">${t.resolved ? 'reopen' : 'resolve'}</button>
        <button class="btn danger wiki-cmt-del" data-id="${esc(t.id)}">del</button>
      </div>
    </div>`;
  }).join('');
  p.querySelectorAll('.wiki-cmt-resolve').forEach(b => b.addEventListener('click', () => _resolveComment(b.dataset.id)));
  p.querySelectorAll('.wiki-cmt-del').forEach(b => b.addEventListener('click', () => _deleteComment(b.dataset.id)));
  p.querySelectorAll('.wiki-cmt-reply-input').forEach(i =>
    i.addEventListener('keydown', e => { if (e.key === 'Enter' && i.value.trim()) _replyComment(i.dataset.id, i.value.trim()); }));
}
// show the "comment" FAB above whatever text is selected (preview OR live editor)
function _onDocSelect() {
  const fab = $('wiki-comment-fab'); if (!fab) return;
  const sel = window.getSelection();
  const text = (sel ? sel.toString() : '').trim();
  if (!text || !_cur) { fab.style.display = 'none'; return; }
  try {
    // sit just past the END of the selection (last line), not over the text — otherwise it
    // covers the selection and blocks right-clicking it. fixed-positioned → viewport coords.
    const rng = sel.getRangeAt(0);
    const rects = rng.getClientRects();
    const end = rects.length ? rects[rects.length - 1] : rng.getBoundingClientRect();
    fab.style.top = `${Math.max(8, end.top - 2)}px`;
    fab.style.left = `${Math.min(window.innerWidth - 96, end.right + 8)}px`;
  } catch {}
  _selText = text.slice(0, 300);
  fab.style.display = 'block';
}
async function _addCommentFromSelection() {
  const fab = $('wiki-comment-fab'); if (fab) fab.style.display = 'none';
  if (!_selText || !_cur) return;
  const body = await dlgPrompt(`comment on “${_selText.slice(0, 40)}${_selText.length > 40 ? '…' : ''}”:`);
  if (!body || !body.trim()) return;
  try {
    await fetch('/api/vault-md/comments', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ path: _cur, anchor: _selText, body: body.trim() }),
    });
    toast('comment added', '');
    const p = $('wiki-comments'); if (p && (p.style.display === 'none' || !p.style.display)) { _closeOtherPanels('wiki-comments'); p.style.display = 'block'; $('wiki-comments-btn')?.classList.add('active'); }
    await loadComments();
  } catch { toast('failed to add comment', 'error'); }
}
async function _replyComment(id, body) {
  try {
    await fetch('/api/vault-md/comments', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ parent_id: id, body }),
    });
    await loadComments();
  } catch { toast('reply failed', 'error'); }
}
async function _resolveComment(id) {
  try { await fetch(`/api/vault-md/comments/${id}/resolve`, { method: 'POST' }); await loadComments(); }
  catch { toast('failed', 'error'); }
}
async function _deleteComment(id) {
  if (!await dlgConfirm('delete this comment thread?')) return;
  try { await fetch(`/api/vault-md/comments/${id}`, { method: 'DELETE' }); await loadComments(); }
  catch { toast('failed', 'error'); }
}
function _applyCommentMarks() {
  const pv = $('wiki-preview'); if (!pv || !_commentAnchors.length) return;
  pv.querySelectorAll('mark.wiki-cmark').forEach(m => { m.replaceWith(...m.childNodes); });
  for (const anchor of _commentAnchors) {
    if (!anchor || anchor.length < 2) continue;
    _markFirst(pv, anchor);
  }
}
function _markFirst(root, text) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
  let node;
  while ((node = walker.nextNode())) {
    if (node.parentElement?.classList.contains('wiki-cmark')) continue;
    const idx = node.nodeValue.indexOf(text);
    if (idx === -1) continue;
    const range = document.createRange();
    range.setStart(node, idx);
    range.setEnd(node, idx + text.length);
    const mark = document.createElement('mark');
    mark.className = 'wiki-cmark';
    try { range.surroundContents(mark); } catch { continue; }
    return;
  }
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
      <button class="btn" id="wiki-q-insert" title="insert as a live query block in the doc">insert block</button>
      <button class="btn" id="wiki-q-save" title="save these filters as a named view">save view</button>
    </div>
    <div class="wiki-q-views" id="wiki-q-views"></div>
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
  $('wiki-q-insert')?.addEventListener('click', insertQueryBlock);
  $('wiki-q-save')?.addEventListener('click', saveView);
  _loadViews();
}

function _qToSpec() {
  const lines = [];
  for (const f of _qFilters) if ((f.field || '').trim()) lines.push(`${f.field.trim()}: ${(f.value || '').trim()}`);
  if (_qSort.field.trim()) lines.push(`sort: ${_qSort.field.trim()} ${_qSort.dir}`);
  return lines.join('\n');
}
function insertQueryBlock() {
  const spec = _qToSpec();
  if (!spec) { toast('add a filter first', 'error'); return; }
  setEditor(getEditor() + '\n```query\n' + spec + '\n```\n');
  queueSave();
  toast('query block inserted', '');
}
async function saveView() {
  const name = await dlgPrompt('name this view:');
  if (!name) return;
  try {
    await fetch('/api/vault-md/views', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name, spec: _qToSpec() }) });
    toast('view saved', '');
  } catch { toast('save failed', 'error'); }
  _loadViews();
}
async function _loadViews() {
  const box = $('wiki-q-views'); if (!box) return;
  let views = [];
  try { views = (await fetch('/api/vault-md/views').then(r => r.json())).views || []; } catch {}
  if (!views.length) { box.innerHTML = ''; return; }
  box.innerHTML = '<span class="wiki-q-views-label">saved:</span> ' + views.map(v =>
    `<span class="wiki-q-view" data-spec="${esc(v.spec)}">${esc(v.name)}</span>`).join(' ');
  box.querySelectorAll('.wiki-q-view').forEach(el => el.addEventListener('click', () => {
    _loadSpecIntoBuilder(el.dataset.spec);
    renderQuery();
  }));
}
function _loadSpecIntoBuilder(spec) {
  _qFilters = []; _qSort = { field: '', dir: 'asc' };
  for (const line of (spec || '').split('\n')) {
    const i = line.indexOf(':'); if (i < 0) continue;
    const k = line.slice(0, i).trim(), v = line.slice(i + 1).trim();
    if (k === 'sort') { const p = v.split(' '); _qSort = { field: p[0] || '', dir: p[1] || 'asc' }; }
    else if (k && k !== 'limit' && k !== 'group') _qFilters.push({ field: k, op: 'eq', value: v });
  }
  if (!_qFilters.length) _qFilters.push({ field: '', op: 'eq', value: '' });
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
    const explainer = '<div class="wiki-bl-explainer">backlinks — other docs that <code>[[link]]</code> to this one; <b>unlinked mentions</b> name it in plain text without a link yet.</div>';
    let html = explainer;
    if (links.length) html += `<div class="wiki-bl-head">${links.length} backlink${links.length > 1 ? 's' : ''}</div>` + links.map(row).join('');
    if (ment.length) html += `<div class="wiki-bl-head wiki-bl-unlinked">${ment.length} unlinked mention${ment.length > 1 ? 's' : ''}</div>` + ment.map(row).join('');
    if (!links.length && !ment.length) html += '<span class="wiki-bl-empty">nothing links here yet — add <code>[[' + esc(name) + ']]</code> in another doc to create a backlink</span>';
    el.innerHTML = html;
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
function toggleTaskRoll() { _togglePanel('wiki-taskroll', 'wiki-taskroll-btn', loadTaskRoll); }
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
  const p = _cur;
  await fetch(`/api/vault-md/file?path=${encodeURIComponent(p)}`, { method: 'DELETE' });
  closeTab(p);   // 3q: drop the deleted doc from the open-tabs strip + switch away
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

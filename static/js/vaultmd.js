// docs: file tree + a CodeMirror live-preview editor + rendered preview, with
// [[wikilinks]], backlinks, embeds, tags, graph, outline, history.
//
// modes (mode button cycles): live = CodeMirror WYSIWYG (markdown symbols hidden,
// styled inline, symbols reveal on the cursor's line) · source = raw markdown
// textarea · preview = fully rendered. CodeMirror edits plain markdown text
// directly (no lossy round-trip), so a save can never corrupt the file.
import { mdToHtml, toast, enhanceMarkdown } from './util.js';
import { prompt as dlgPrompt, confirm as dlgConfirm } from './dialog.js';

let _cur = null;
let _saveT = 0;
let _inited = false;

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const _syncEmpty = () => $('wiki-view')?.classList.toggle('no-note', !_cur);

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
        if (!_applyingExternal) queueSave();
      },
    });
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
  if (_docsMode === 'preview') renderPreview();
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
  $('wiki-export-btn')?.addEventListener('click', exportDocx);
  $('wiki-folder-btn')?.addEventListener('click', newFolder);
  $('wiki-today-btn')?.addEventListener('click', openDaily);
  $('wiki-outline-btn')?.addEventListener('click', toggleOutline);
  $('wiki-todos-btn')?.addEventListener('click', extractTodos);
  $('wiki-history-btn')?.addEventListener('click', toggleHistory);
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
    el.innerHTML = t.items.length ? renderItems(t.items, 0) : '<div class="wiki-empty">docs empty - create one</div>';
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

function _rowActs() {
  return `<span class="wiki-row-acts"><button class="wiki-row-act" data-act="rename" title="rename">✎</button><button class="wiki-row-act" data-act="delete" title="delete">✕</button></span>`;
}
function renderItems(items, depth) {
  return items.map(it => {
    const pad = `style="padding-left:${0.4 + depth * 0.7}rem"`;
    if (it.type === 'dir') {
      return `<div class="wiki-dir" data-path="${esc(it.path)}" ${pad}><span class="wiki-row-label">▸ ${esc(it.name)}</span>${_rowActs()}</div>`
        + renderItems(it.children || [], depth + 1);
    }
    const active = it.path === _cur ? ' active' : '';
    return `<div class="wiki-file${active}" data-path="${esc(it.path)}" ${pad}><span class="wiki-row-label">${esc(it.name)}</span>${_rowActs()}</div>`;
  }).join('');
}
function _wireRow(row, kind) {
  row.querySelector('.wiki-row-label')?.addEventListener('click', () => { if (kind === 'file') openFile(row.dataset.path); });
  row.querySelectorAll('.wiki-row-act').forEach(b => b.addEventListener('click', async e => {
    e.stopPropagation();
    const path = row.dataset.path;
    if (b.dataset.act === 'rename') {
      const cur = path.split('/').pop().replace(/\.md$/, '');
      const name = await dlgPrompt(`rename ${kind}:`, cur);
      if (!name?.trim() || name.trim() === cur) return;
      const parent = path.includes('/') ? path.slice(0, path.lastIndexOf('/') + 1) : '';
      await fetch('/api/vault-md/rename', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path, new_path: parent + name.trim() }) });
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
    <div style="display:flex;align-items:center;gap:0.5rem;padding:0.25rem 0;font-size:0.72rem">
      <span>${_revAgo(r.created_at)}</span><span style="color:var(--muted)">${(r.size / 1000).toFixed(1)}k</span><span style="flex:1"></span>
      <button class="btn" data-rev-restore="${r.id}" style="font-size:0.66rem">restore</button>
    </div>`).join('');
  panel.querySelectorAll('[data-rev-restore]').forEach(b => b.addEventListener('click', async () => {
    if (!await dlgConfirm('restore this version? the current state is kept as a revision.')) return;
    try {
      const r = await fetch(`/api/vault-md/revisions/${b.dataset.revRestore}/restore`, { method: 'POST' });
      if (!r.ok) throw new Error();
      await openFile(_cur); toast('version restored', 'success'); loadHistory();
    } catch { toast('restore failed', 'error'); }
  }));
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

async function openDaily() {
  const d = new Date();
  const name = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  await fetch('/api/vault-md/file', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path: name, content: `# ${name}\n\n` }) });
  await loadTree();
  openFile(name + '.md');
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
  try {
    const d = await fetch(`/api/vault-md/backlinks?name=${encodeURIComponent(name)}`).then(r => r.json());
    const el = $('wiki-backlinks');
    if (!d.backlinks.length) { el.innerHTML = '<span class="wiki-bl-empty">no backlinks</span>'; return; }
    el.innerHTML = `<div class="wiki-bl-head">${d.backlinks.length} backlink${d.backlinks.length > 1 ? 's' : ''}</div>` +
      d.backlinks.map(b => `<div class="wiki-bl" data-path="${esc(b.path)}"><b>${esc(b.name)}</b> <span>${esc(b.context)}</span></div>`).join('');
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

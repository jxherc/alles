// spatial canvas / whiteboard (2d). nodes are draggable cards; edges are arrows
// between them; layout persists to a .canvas JSON file in the vault. pan by dragging
// empty space. a node can link to a note (click opens it).
import { toast } from './util.js';
import { prompt as dlgPrompt } from './dialog.js';

const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const uid = () => 'n' + Math.random().toString(36).slice(2, 9);

let _path = null, _nodes = [], _edges = [], _saveT = 0;
let _pan = { x: 0, y: 0 };
let _connectFrom = null;
let _openNote = null;   // injected callback to open a note by name

export function setCanvasNoteOpener(fn) { _openNote = fn; }

export async function openCanvas(path) {
  _path = path.endsWith('.canvas') ? path : path + '.canvas';
  let d;
  try { d = await fetch('/api/vault-md/canvas?path=' + encodeURIComponent(_path)).then(r => r.json()); }
  catch { d = { nodes: [], edges: [] }; }
  _nodes = d.nodes || []; _edges = d.edges || []; _pan = { x: 0, y: 0 }; _connectFrom = null;
  $('canvas-view').style.display = 'flex';
  $('canvas-title').textContent = _path.replace(/\.canvas$/, '');
  render();
}

function closeCanvas() { if ($('canvas-view')) $('canvas-view').style.display = 'none'; }

function save() {
  clearTimeout(_saveT);
  _saveT = setTimeout(() => {
    fetch('/api/vault-md/canvas', {
      method: 'PUT', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ path: _path, nodes: _nodes, edges: _edges }),
    }).catch(() => toast('canvas save failed', 'error'));
  }, 350);
}

function _nodeById(id) { return _nodes.find(n => n.id === id); }

function render() {
  const surf = $('canvas-surface'); if (!surf) return;
  const edgeSvg = _edges.map(e => {
    const a = _nodeById(e.from), b = _nodeById(e.to);
    if (!a || !b) return '';
    const x1 = a.x + _pan.x + 70, y1 = a.y + _pan.y + 22, x2 = b.x + _pan.x + 70, y2 = b.y + _pan.y + 22;
    return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="var(--accent)" stroke-width="1.5" marker-end="url(#cv-arrow)"/>`;
  }).join('');
  const nodeHtml = _nodes.map(n => `
    <div class="canvas-node${n.note ? ' is-note' : ''}" data-id="${esc(n.id)}" style="left:${n.x + _pan.x}px;top:${n.y + _pan.y}px">
      <div class="canvas-node-body">${esc(n.note ? '🔗 ' + n.note : (n.text || ''))}</div>
      <span class="canvas-node-link" title="connect">↔</span>
      <span class="canvas-node-del" title="delete">×</span>
    </div>`).join('');
  surf.innerHTML = `<svg class="canvas-edges"><defs><marker id="cv-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6" fill="var(--accent)"/></marker></defs>${edgeSvg}</svg>${nodeHtml}`;
  surf.querySelectorAll('.canvas-node').forEach(el => _wireNode(el));
}

function _wireNode(el) {
  const n = _nodeById(el.dataset.id);
  if (!n) return;
  // open a note node / edit a text node
  el.querySelector('.canvas-node-body').addEventListener('click', e => {
    if (_dragging) return;
    if (n.note && _openNote) { _openNote(n.note); closeCanvas(); return; }
  });
  el.querySelector('.canvas-node-body').addEventListener('dblclick', async () => {
    if (n.note) return;
    const t = await dlgPrompt('node text:', n.text || '');
    if (t != null) { n.text = t; save(); render(); }
  });
  el.querySelector('.canvas-node-del').addEventListener('click', e => {
    e.stopPropagation();
    _nodes = _nodes.filter(x => x.id !== n.id);
    _edges = _edges.filter(x => x.from !== n.id && x.to !== n.id);
    save(); render();
  });
  el.querySelector('.canvas-node-link').addEventListener('click', e => {
    e.stopPropagation();
    if (!_connectFrom) { _connectFrom = n.id; el.classList.add('connecting'); toast('click another node\'s ↔ to connect', ''); }
    else if (_connectFrom !== n.id) {
      _edges.push({ from: _connectFrom, to: n.id }); _connectFrom = null; save(); render();
    } else { _connectFrom = null; render(); }
  });
  _makeDraggable(el, n);
}

let _dragging = false;
function _makeDraggable(el, n) {
  el.addEventListener('mousedown', e => {
    if (e.target.closest('.canvas-node-del, .canvas-node-link')) return;
    e.preventDefault();
    const sx = e.clientX, sy = e.clientY, ox = n.x, oy = n.y;
    _dragging = false;
    const move = ev => {
      if (Math.abs(ev.clientX - sx) + Math.abs(ev.clientY - sy) > 3) _dragging = true;
      n.x = ox + (ev.clientX - sx); n.y = oy + (ev.clientY - sy);
      // move the element directly during drag so it doesn't detach (no full re-render)
      el.style.left = (n.x + _pan.x) + 'px'; el.style.top = (n.y + _pan.y) + 'px';
    };
    const up = () => {
      document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up);
      if (_dragging) { save(); render(); }   // re-render to redraw edges to the new position
      setTimeout(() => { _dragging = false; }, 50);
    };
    document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
  });
}

export function initCanvas() {
  if (!$('canvas-view')) return;
  $('canvas-close')?.addEventListener('click', closeCanvas);
  $('canvas-add')?.addEventListener('click', () => {
    _nodes.push({ id: uid(), x: 60 - _pan.x + Math.round(Math.random() * 80), y: 60 - _pan.y + Math.round(Math.random() * 80), text: 'new node' });
    save(); render();
  });
  $('canvas-add-note')?.addEventListener('click', async () => {
    const name = await dlgPrompt('link which note (name)?');
    if (!name) return;
    _nodes.push({ id: uid(), x: 80 - _pan.x, y: 80 - _pan.y, note: name });
    save(); render();
  });
  // pan by dragging the empty surface
  const surf = $('canvas-surface');
  surf?.addEventListener('mousedown', e => {
    if (e.target !== surf && !e.target.classList.contains('canvas-edges')) return;
    const sx = e.clientX, sy = e.clientY, ox = _pan.x, oy = _pan.y;
    const move = ev => { _pan.x = ox + (ev.clientX - sx); _pan.y = oy + (ev.clientY - sy); render(); };
    const up = () => { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); };
    document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
  });
}

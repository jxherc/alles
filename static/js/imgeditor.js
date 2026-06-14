// canvas image editor — adjustments, crop, rotate/flip, brush, text, undo, save.
// pure browser Canvas API, no deps. opens as a full-screen modal over an image url.
import { toast } from './util.js';

let S = null;   // editor state

export function openEditor(url, opts = {}) {
  let modal = document.getElementById('imgeditor-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'imgeditor-modal';
    modal.className = 'ie-modal';
    document.body.appendChild(modal);
  }
  modal.style.display = 'flex';
  modal.innerHTML = `
    <div class="ie-shell">
      <div class="ie-bar">
        <div class="ie-tools">
          <button class="ie-tool active" data-tool="adjust" title="adjust">adjust</button>
          <button class="ie-tool" data-tool="crop" title="crop">crop</button>
          <button class="ie-tool" data-tool="brush" title="draw">draw</button>
          <button class="ie-tool" data-tool="text" title="text">text</button>
          <span class="ie-sep"></span>
          <button class="ie-btn" data-act="rotl" title="rotate left">⟲</button>
          <button class="ie-btn" data-act="rotr" title="rotate right">⟳</button>
          <button class="ie-btn" data-act="fliph" title="flip horizontal">⇆</button>
          <button class="ie-btn" data-act="flipv" title="flip vertical">⇅</button>
          <span class="ie-sep"></span>
          <button class="ie-btn" data-act="undo" title="undo">undo</button>
          <button class="ie-btn" data-act="reset" title="reset adjustments">reset</button>
        </div>
        <div class="ie-right">
          <button class="ie-btn" data-act="download">download</button>
          <button class="ie-btn primary" data-act="save">save to gallery</button>
          <button class="ie-btn" data-act="close">✕</button>
        </div>
      </div>
      <div class="ie-body">
        <div class="ie-panel" id="ie-panel"></div>
        <div class="ie-stage" id="ie-stage">
          <div class="ie-canvas-wrap" id="ie-canvas-wrap">
            <canvas id="ie-canvas"></canvas>
            <div class="ie-crop-rect" id="ie-crop-rect" style="display:none"></div>
          </div>
        </div>
      </div>
    </div>`;

  const canvas = modal.querySelector('#ie-canvas');
  S = {
    modal, canvas, ctx: canvas.getContext('2d'),
    adjust: { b: 100, c: 100, s: 100, gray: false, sepia: false },
    tool: 'adjust', brush: { size: 8, color: '#ff3b30' },
    drawing: false, lastX: 0, lastY: 0,
    crop: null, history: [],
    name: opts.name || 'edited.png', onSaved: opts.onSaved || null,
  };

  const img = new Image();
  img.onload = () => {
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    S.ctx.drawImage(img, 0, 0);
    applyFilter();
    renderPanel();
  };
  img.onerror = () => toast('couldn’t load the image', 'error');
  img.src = url;

  modal.querySelector('.ie-tools').addEventListener('click', e => {
    const t = e.target.closest('.ie-tool');
    if (t) { setTool(t.dataset.tool); return; }
    const b = e.target.closest('.ie-btn');
    if (b) act(b.dataset.act);
  });
  modal.querySelector('.ie-right').addEventListener('click', e => {
    const b = e.target.closest('.ie-btn'); if (b) act(b.dataset.act);
  });
  wireCanvas();
}

function filterStr() {
  const a = S.adjust;
  return `brightness(${a.b}%) contrast(${a.c}%) saturate(${a.s}%)`
    + (a.gray ? ' grayscale(1)' : '') + (a.sepia ? ' sepia(1)' : '');
}
function applyFilter() { S.canvas.style.filter = filterStr(); }

function setTool(tool) {
  S.tool = tool;
  S.modal.querySelectorAll('.ie-tool').forEach(t => t.classList.toggle('active', t.dataset.tool === tool));
  S.modal.querySelector('#ie-crop-rect').style.display = 'none';
  S.crop = null;
  S.canvas.style.cursor = (tool === 'brush' || tool === 'text') ? 'crosshair' : (tool === 'crop' ? 'cell' : 'default');
  renderPanel();
}

function renderPanel() {
  const p = S.modal.querySelector('#ie-panel');
  if (!p) return;
  if (S.tool === 'adjust') {
    const a = S.adjust;
    p.innerHTML = `
      ${slider('brightness', 'b', a.b)}
      ${slider('contrast', 'c', a.c)}
      ${slider('saturation', 's', a.s)}
      <label class="ie-chk"><input type="checkbox" id="ie-gray" ${a.gray ? 'checked' : ''}> grayscale</label>
      <label class="ie-chk"><input type="checkbox" id="ie-sepia" ${a.sepia ? 'checked' : ''}> sepia</label>`;
    p.querySelectorAll('input[type=range]').forEach(r => r.addEventListener('input', () => {
      S.adjust[r.dataset.k] = +r.value;
      r.nextElementSibling.textContent = r.value;
      applyFilter();
    }));
    p.querySelector('#ie-gray').onchange = e => { S.adjust.gray = e.target.checked; applyFilter(); };
    p.querySelector('#ie-sepia').onchange = e => { S.adjust.sepia = e.target.checked; applyFilter(); };
  } else if (S.tool === 'brush') {
    p.innerHTML = `
      ${slider('brush size', 'size', S.brush.size, 1, 80)}
      <label class="ie-field">color <input type="color" id="ie-color" value="${S.brush.color}"></label>`;
    p.querySelector('input[type=range]').addEventListener('input', e => {
      S.brush.size = +e.target.value; e.target.nextElementSibling.textContent = e.target.value;
    });
    p.querySelector('#ie-color').onchange = e => { S.brush.color = e.target.value; };
  } else if (S.tool === 'crop') {
    p.innerHTML = `<div class="ie-hint">drag a box on the image, then</div>
      <button class="ie-btn primary" id="ie-apply-crop">apply crop</button>`;
    p.querySelector('#ie-apply-crop').onclick = applyCrop;
  } else {
    p.innerHTML = `<div class="ie-hint">click on the image to drop text</div>`;
  }
}

function slider(label, k, val, min = 0, max = 200) {
  return `<label class="ie-field">${label}
    <input type="range" data-k="${k}" min="${min}" max="${max}" value="${val}"><span>${val}</span></label>`;
}

function snapshot() {
  const c = document.createElement('canvas');
  c.width = S.canvas.width; c.height = S.canvas.height;
  c.getContext('2d').drawImage(S.canvas, 0, 0);
  S.history.push(c);
  if (S.history.length > 24) S.history.shift();
}
function restore(c) {
  S.canvas.width = c.width; S.canvas.height = c.height;
  S.ctx.clearRect(0, 0, c.width, c.height);
  S.ctx.drawImage(c, 0, 0);
}

function act(a) {
  if (a === 'close') { S.modal.style.display = 'none'; S = null; return; }
  if (a === 'undo') { const c = S.history.pop(); if (c) restore(c); else toast('nothing to undo'); return; }
  if (a === 'reset') { S.adjust = { b: 100, c: 100, s: 100, gray: false, sepia: false }; applyFilter(); renderPanel(); return; }
  if (a === 'rotl') return rotate(-90);
  if (a === 'rotr') return rotate(90);
  if (a === 'fliph') return flip('h');
  if (a === 'flipv') return flip('v');
  if (a === 'download') return exportImage(true);
  if (a === 'save') return exportImage(false);
}

function rotate(deg) {
  snapshot();
  const src = S.canvas, swap = Math.abs(deg) === 90;
  const c = document.createElement('canvas');
  c.width = swap ? src.height : src.width;
  c.height = swap ? src.width : src.height;
  const x = c.getContext('2d');
  x.translate(c.width / 2, c.height / 2);
  x.rotate(deg * Math.PI / 180);
  x.drawImage(src, -src.width / 2, -src.height / 2);
  restore(c);
}
function flip(axis) {
  snapshot();
  const src = S.canvas;
  const c = document.createElement('canvas');
  c.width = src.width; c.height = src.height;
  const x = c.getContext('2d');
  x.translate(axis === 'h' ? c.width : 0, axis === 'v' ? c.height : 0);
  x.scale(axis === 'h' ? -1 : 1, axis === 'v' ? -1 : 1);
  x.drawImage(src, 0, 0);
  restore(c);
}

function coords(e) {
  const r = S.canvas.getBoundingClientRect();
  return [(e.clientX - r.left) / r.width * S.canvas.width,
          (e.clientY - r.top) / r.height * S.canvas.height];
}

function wireCanvas() {
  const cv = S.canvas, rect = S.modal.querySelector('#ie-crop-rect');
  let cropStart = null;
  cv.addEventListener('mousedown', e => {
    const [x, y] = coords(e);
    if (S.tool === 'brush') {
      snapshot(); S.drawing = true; [S.lastX, S.lastY] = [x, y];
    } else if (S.tool === 'text') {
      const txt = prompt('text:'); if (!txt) return;
      snapshot();
      const size = Math.max(16, Math.round(S.canvas.height / 18));
      S.ctx.fillStyle = S.brush.color; S.ctx.font = `bold ${size}px Inter, sans-serif`;
      S.ctx.textBaseline = 'top'; S.ctx.fillText(txt, x, y);
    } else if (S.tool === 'crop') {
      cropStart = { sx: e.clientX, sy: e.clientY };
      S.crop = null;
    }
  });
  window.addEventListener('mousemove', e => {
    if (S.drawing && S.tool === 'brush') {
      const [x, y] = coords(e);
      const ctx = S.ctx;
      ctx.strokeStyle = S.brush.color; ctx.lineWidth = S.brush.size;
      ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.beginPath(); ctx.moveTo(S.lastX, S.lastY); ctx.lineTo(x, y); ctx.stroke();
      [S.lastX, S.lastY] = [x, y];
    } else if (cropStart) {
      const wrap = S.modal.querySelector('#ie-canvas-wrap').getBoundingClientRect();
      const x1 = Math.min(cropStart.sx, e.clientX), y1 = Math.min(cropStart.sy, e.clientY);
      const w = Math.abs(e.clientX - cropStart.sx), h = Math.abs(e.clientY - cropStart.sy);
      rect.style.display = 'block';
      rect.style.left = (x1 - wrap.left) + 'px'; rect.style.top = (y1 - wrap.top) + 'px';
      rect.style.width = w + 'px'; rect.style.height = h + 'px';
      const cr = S.canvas.getBoundingClientRect();
      S.crop = {
        x: (x1 - cr.left) / cr.width * S.canvas.width,
        y: (y1 - cr.top) / cr.height * S.canvas.height,
        w: w / cr.width * S.canvas.width,
        h: h / cr.height * S.canvas.height,
      };
    }
  });
  window.addEventListener('mouseup', () => { S.drawing = false; cropStart = null; });
}

function applyCrop() {
  if (!S.crop || S.crop.w < 4 || S.crop.h < 4) { toast('drag a box first'); return; }
  snapshot();
  const { x, y, w, h } = S.crop;
  const c = document.createElement('canvas');
  c.width = Math.round(w); c.height = Math.round(h);
  c.getContext('2d').drawImage(S.canvas, Math.round(x), Math.round(y), Math.round(w), Math.round(h), 0, 0, Math.round(w), Math.round(h));
  restore(c);
  S.modal.querySelector('#ie-crop-rect').style.display = 'none';
  S.crop = null;
}

// bake the live adjustment filter into the pixels, return a data url
function flatten() {
  const out = document.createElement('canvas');
  out.width = S.canvas.width; out.height = S.canvas.height;
  const x = out.getContext('2d');
  x.filter = filterStr();
  x.drawImage(S.canvas, 0, 0);
  return out.toDataURL('image/png');
}

async function exportImage(download) {
  const dataUrl = flatten();
  if (download) {
    const a = document.createElement('a');
    a.href = dataUrl; a.download = S.name.replace(/\.\w+$/, '') + '-edited.png'; a.click();
    return;
  }
  try {
    const r = await fetch('/api/photos/edit-save', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ data_url: dataUrl, name: S.name }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'save failed');
    toast('saved to gallery', 'success');
    const cb = S.onSaved;
    S.modal.style.display = 'none'; S = null;
    if (cb) cb();
  } catch (e) {
    toast(e.message || 'save failed', 'error');
  }
}

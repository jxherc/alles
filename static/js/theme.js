// advanced theme system for alles — presets, full per-color editing, fonts, density,
// animated backgrounds, frosted glass, custom themes, import/export. colors map to the
// alles tokens: bg / text / panel / faint / accent. pure color algos + the canvas
// patterns are ported from odysseus; the editor UI + apply engine are alles-native.
import { initColorPickers } from './colorpicker.js';
import { generateHarmony, lum as _lum, mix as _mix, mutedFor as _mutedFor } from './color.js';
import { toast } from './util.js';
export { generateHarmony };

const LS_KEY = 'alles-appearance';

// presets: {bg,text,panel,faint,accent} (+ optional default pattern)
export const PRESETS = {
  dark:      { colors: { bg:'#0a0a0a', text:'#e8e6e3', panel:'#0e0e0e', faint:'#2e2e2e', accent:'#818cf8' } },
  light:     { colors: { bg:'#f5f4f1', text:'#111111', panel:'#efede9', faint:'#d4d2ce', accent:'#818cf8' } },
  midnight:  { colors: { bg:'#0d1117', text:'#c9d1d9', panel:'#161b22', faint:'#30363d', accent:'#58a6ff' }, pattern:'rain' },
  paper:     { colors: { bg:'#faf8f5', text:'#3b3836', panel:'#ffffff', faint:'#d5d0c8', accent:'#b07d3a' }, pattern:'dots' },
  cyberpunk: { colors: { bg:'#0a0a0f', text:'#0ff0fc', panel:'#12101a', faint:'#9b30ff', accent:'#e040fb' }, pattern:'synapse' },
  retrowave: { colors: { bg:'#1a1a2e', text:'#e0d6f5', panel:'#16213e', faint:'#533483', accent:'#e94560' } },
  forest:    { colors: { bg:'#1b2a1b', text:'#a8d5a2', panel:'#142414', faint:'#3d6b3d', accent:'#7cb871' }, pattern:'petals' },
  ocean:     { colors: { bg:'#0b1a2c', text:'#cfe8ff', panel:'#091422', faint:'#1e5074', accent:'#4facfe' }, pattern:'constellations' },
  ume:       { colors: { bg:'#2b1b2e', text:'#f5c2e7', panel:'#1e1420', faint:'#6c4675', accent:'#f5a0c0' }, pattern:'petals' },
  copper:    { colors: { bg:'#1c1410', text:'#e8c39e', panel:'#140f0a', faint:'#7a5533', accent:'#d4764e' } },
  terminal:  { colors: { bg:'#000000', text:'#00ff41', panel:'#0a0a0a', faint:'#003b00', accent:'#00ff41' } },
  organs:    { colors: { bg:'#0a0406', text:'#efe1c8', panel:'#15080a', faint:'#3a1519', accent:'#c83240' }, pattern:'rain' },
  lavender:  { colors: { bg:'#f3eef8', text:'#3d3551', panel:'#faf7ff', faint:'#cec3de', accent:'#9b6dcc' } },
  gpt:       { colors: { bg:'#212121', text:'#ececec', panel:'#171717', faint:'#424242', accent:'#10a37f' } },
  claude:    { colors: { bg:'#262624', text:'#f5f4f0', panel:'#30302e', faint:'#4a4a47', accent:'#c6613f' } },
  cute:      { colors: { bg:'#fff0f5', text:'#d4608a', panel:'#fff8fa', faint:'#f0c0d0', accent:'#ff6b9d' }, pattern:'sparkles' },

  // ── second wave: editor-friendly classics + showcases for the new effects ──
  nord:        { colors: { bg:'#2e3440', text:'#d8dee9', panel:'#272c36', faint:'#434c5e', accent:'#88c0d0' }, pattern:'snow' },
  dracula:     { colors: { bg:'#282a36', text:'#f8f8f2', panel:'#21222c', faint:'#44475a', accent:'#bd93f9' }, pattern:'sparkles' },
  solarized:   { colors: { bg:'#002b36', text:'#93a1a1', panel:'#073642', faint:'#586e75', accent:'#268bd2' } },
  solarlight:  { colors: { bg:'#fdf6e3', text:'#586e75', panel:'#eee8d5', faint:'#cfc7ac', accent:'#268bd2' } },
  gruvbox:     { colors: { bg:'#282828', text:'#ebdbb2', panel:'#1d2021', faint:'#504945', accent:'#fabd2f' } },
  monokai:     { colors: { bg:'#272822', text:'#f8f8f2', panel:'#1e1f1c', faint:'#49483e', accent:'#a6e22e' } },
  tokyo:       { colors: { bg:'#1a1b26', text:'#a9b1d6', panel:'#16161e', faint:'#414868', accent:'#7aa2f7' }, pattern:'rain' },
  catppuccin:  { colors: { bg:'#1e1e2e', text:'#cdd6f4', panel:'#181825', faint:'#45475a', accent:'#cba6f7' }, pattern:'fireflies' },
  rosepine:    { colors: { bg:'#191724', text:'#e0def4', panel:'#1f1d2e', faint:'#403d52', accent:'#ebbcba' }, pattern:'petals' },
  everforest:  { colors: { bg:'#2b3339', text:'#d3c6aa', panel:'#232a2e', faint:'#4a555b', accent:'#a7c080' }, pattern:'petals' },
  sunset:      { colors: { bg:'#1a1014', text:'#ffd9c0', panel:'#150c10', faint:'#5a3040', accent:'#ff7e5f' }, pattern:'embers' },
  sakura:      { colors: { bg:'#fff0f3', text:'#5c3a44', panel:'#ffe5ea', faint:'#f0c8d2', accent:'#ff85a1' }, pattern:'petals' },
  mint:        { colors: { bg:'#0e1a17', text:'#c0f0e0', panel:'#0a1410', faint:'#2a4a40', accent:'#3dd9a8' }, pattern:'bubbles' },
  amber:       { colors: { bg:'#1a1408', text:'#ffe0a0', panel:'#140f06', faint:'#5a4520', accent:'#ffb800' }, pattern:'embers' },
  crimson:     { colors: { bg:'#14080a', text:'#f0c8cc', panel:'#0e0608', faint:'#4a1820', accent:'#e0294a' }, pattern:'embers' },
  indigo:      { colors: { bg:'#0c0e1a', text:'#c8cef0', panel:'#080a14', faint:'#28304a', accent:'#6470ff' }, pattern:'starfield' },
  arctic:      { colors: { bg:'#0e1622', text:'#cfe3f5', panel:'#0a1018', faint:'#284058', accent:'#6ec5ff' }, pattern:'snow' },
  blossom:     { colors: { bg:'#faf4f6', text:'#4a2c34', panel:'#ffffff', faint:'#e8ccd4', accent:'#d6537a' } },
  sand:        { colors: { bg:'#f3ecdf', text:'#4a4136', panel:'#fbf6ec', faint:'#d8cdb8', accent:'#b8893a' }, pattern:'dots' },
  slate:       { colors: { bg:'#11151a', text:'#c5ccd4', panel:'#0c0f13', faint:'#2c343e', accent:'#9aa7b5' } },
  graphite:    { colors: { bg:'#0a0a0a', text:'#e8e6e3', panel:'#0e0e0e', faint:'#2e2e2e', accent:'#e8e6e3' }, pattern:'grid' },
  neon:        { colors: { bg:'#0a0014', text:'#e0c0ff', panel:'#0e001a', faint:'#3a0a5a', accent:'#c030ff' }, pattern:'synapse' },
  matrix:      { colors: { bg:'#000a00', text:'#39ff14', panel:'#001400', faint:'#0a3a0a', accent:'#39ff14' }, pattern:'matrix' },
  vapor:       { colors: { bg:'#1b0f2e', text:'#f0d0ff', panel:'#15082a', faint:'#4a2a6a', accent:'#ff6ad5' }, pattern:'waves' },
  coral:       { colors: { bg:'#fff5f0', text:'#5a3a32', panel:'#ffffff', faint:'#f0d0c4', accent:'#ff6b4a' } },
  deepsea:     { colors: { bg:'#021018', text:'#a0e0e8', panel:'#01080e', faint:'#0a3848', accent:'#18c0d8' }, pattern:'bubbles' },
  wine:        { colors: { bg:'#1a0c14', text:'#e8c0d4', panel:'#140810', faint:'#4a1c34', accent:'#c0407a' } },
  moss:        { colors: { bg:'#10180e', text:'#cae0b0', panel:'#0c1209', faint:'#2e4426', accent:'#8cc04a' }, pattern:'fireflies' },
  steel:       { colors: { bg:'#eef1f4', text:'#2a3038', panel:'#ffffff', faint:'#cdd4dc', accent:'#4a6f9c' } },
  ember:       { colors: { bg:'#120a06', text:'#f0c8a0', panel:'#0c0704', faint:'#4a3018', accent:'#ff8c32' }, pattern:'embers' },
  orchid:      { colors: { bg:'#160c1c', text:'#e8c8f0', panel:'#100818', faint:'#3e2050', accent:'#b060e0' }, pattern:'fireflies' },
  ice:         { colors: { bg:'#eef6fb', text:'#24414f', panel:'#ffffff', faint:'#c8dce8', accent:'#2a9fd0' }, pattern:'snow' },
  abyss:       { colors: { bg:'#070b18', text:'#b8c4e0', panel:'#040712', faint:'#1e2840', accent:'#5878d0' }, pattern:'starfield' },
  peach:       { colors: { bg:'#fff3e8', text:'#5a3e2a', panel:'#ffffff', faint:'#f0d6bc', accent:'#f08a3a' } },
  cobalt:      { colors: { bg:'#0a1626', text:'#c8dcf0', panel:'#06101c', faint:'#1e3850', accent:'#3a8fd8' }, pattern:'waves' },
  lime:        { colors: { bg:'#0e1408', text:'#d8f0b0', panel:'#0a0f04', faint:'#2e4018', accent:'#a8e020' }, pattern:'fireflies' },
};

const FONT_MAP = {
  sans: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
  mono: "'JetBrains Mono', ui-monospace, 'SF Mono', monospace",
  serif: "Georgia, 'Times New Roman', serif",
};

const DEFAULT = () => ({
  preset: 'dark', colors: { ...PRESETS.dark.colors },
  font: 'sans', density: 'comfortable', bgPattern: 'none', frosted: false,
  effect: { color: '', intensity: 1, size: 1 }, customThemes: {},
});

// colour math (hexToRgb/HSL, hslToHex, _mix, _lum, generateHarmony) now lives in
// ./color.js so it can be unit-tested in node without a browser.

// ── apply engine ────────────────────────────────────────────────────────────────
export function applyAppearance(a) {
  a = a || loadLocal();
  const c = a.colors || PRESETS.dark.colors;
  const root = document.documentElement;
  const set = (k, v) => { if (v) root.style.setProperty(k, v); };
  set('--bg', c.bg); set('--text', c.text); set('--panel', c.panel); set('--faint', c.faint); set('--accent', c.accent);
  if (c.text && c.bg) root.style.setProperty('--muted', _mutedFor(c.text, c.bg, c.panel || c.bg));
  if (c.bg) (_lum(c.bg) > 0.5) ? (root.dataset.theme = 'light') : delete root.dataset.theme;
  root.style.setProperty('--font-family', FONT_MAP[a.font] || FONT_MAP.sans);
  root.classList.remove('density-compact', 'density-spacious');
  if (a.density && a.density !== 'comfortable') root.classList.add('density-' + a.density);
  if (document.body) document.body.classList.toggle('theme-frosted', !!a.frosted);
  const eff = a.effect || {};
  root.style.setProperty('--bg-effect-color', eff.color || '');
  root.style.setProperty('--bg-effect-intensity', String(eff.intensity == null ? 1 : eff.intensity));
  root.style.setProperty('--bg-effect-size', String(eff.size == null ? 1 : eff.size));
  applyBgPattern(a.bgPattern || 'none');
  const mtc = document.querySelector('meta[name="theme-color"]');
  if (mtc && c.bg) mtc.setAttribute('content', c.bg);
  window._updateFavicon?.();
}

// ── storage ─────────────────────────────────────────────────────────────────────
export function loadLocal() {
  try { const o = JSON.parse(localStorage.getItem(LS_KEY) || 'null'); if (o && o.colors) return { ...DEFAULT(), ...o }; } catch { /* bad json */ }
  return DEFAULT();
}
function saveLocal(a) { try { localStorage.setItem(LS_KEY, JSON.stringify(a)); } catch { /* quota */ } }

let _saveTimer = null;
function save(a) {
  saveLocal(a);
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(() => {
    fetch('/api/appearance', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(a) }).catch(() => {});
  }, 350);
}

// called at boot: apply the cached theme instantly, then reconcile with the server.
// only let the server win when it actually has a stored theme (_stored) — or when we
// have no local cache yet — so an in-flight PUT can't be clobbered by a default response.
export async function initAppearance() {
  const hadLocal = !!localStorage.getItem(LS_KEY);
  applyAppearance(loadLocal());
  try {
    const s = await fetch('/api/appearance').then(r => r.json());
    if (s && s.colors && (s._stored || !hadLocal)) {
      delete s._stored;
      saveLocal(s);
      applyAppearance(s);
    }
  } catch { /* offline — keep local */ }
}

// ── background patterns ───────────────────────────────────────────────────────────
// canvas-driven ones (react to effect color/intensity/size) and pure-CSS ones.
const _CANVAS = {
  synapse: _initSynapse, rain: _initRain, constellations: _initConstellations,
  sparkles: _initSparkles, petals: _initPetals, snow: _initSnow, embers: _initEmbers,
  fireflies: _initFireflies, bubbles: _initBubbles, starfield: _initStarfield,
  matrix: _initMatrix, aurora: _initAurora, waves: _initWaves,
};
const CSS_ONLY = ['dots', 'grid', 'crosshatch', 'scanlines'];
// every pattern that uses the body.bg-pattern-* class (canvas loops check it to self-stop)
const ALL_PATTERNS = [...CSS_ONLY, ...Object.keys(_CANVAS)];
const _BG_CLASSES = ALL_PATTERNS.map(p => 'bg-pattern-' + p);
const _CANVAS_SEL = Object.keys(_CANVAS).map(k => '#' + k + '-canvas').join(',');

export function applyBgPattern(pattern) {
  const p = pattern || 'none';
  if (!document.body) return;
  document.body.classList.remove(..._BG_CLASSES);
  document.querySelectorAll(_CANVAS_SEL).forEach(c => c.remove());
  if (p !== 'none') document.body.classList.add('bg-pattern-' + p);
  if (_CANVAS[p]) _CANVAS[p]();
}

function _effSize() { const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--bg-effect-size')); return isNaN(v) ? 1 : v; }
function _effInten() { const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--bg-effect-intensity')); return isNaN(v) ? 1 : v; }
function _effColor() {
  const s = getComputedStyle(document.documentElement);
  return s.getPropertyValue('--bg-effect-color').trim() || s.getPropertyValue('--text').trim() || '#9cdef2';
}
function _mkCanvas(id) {
  const canvas = document.createElement('canvas');
  canvas.id = id;
  canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);
  return canvas;
}

function _initSynapse() {
  const canvas = _mkCanvas('synapse-canvas'), ctx = canvas.getContext('2d'), dpr = Math.min(devicePixelRatio || 1, 2);
  const GRID = 24; let W, H, cols, rows; const pulses = [];
  const resize = () => { W = innerWidth; H = innerHeight; canvas.width = W * dpr; canvas.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); cols = Math.ceil(W / GRID); rows = Math.ceil(H / GRID); };
  resize(); const onR = () => resize(); addEventListener('resize', onR);
  const spawn = () => { const sp = 2 + Math.random() * 20; if (Math.random() > 0.5) pulses.push({ x: -12, y: Math.floor(Math.random() * (rows + 1)) * GRID, dx: sp, dy: 0 }); else pulses.push({ x: Math.floor(Math.random() * (cols + 1)) * GRID, y: -12, dx: 0, dy: sp }); };
  const draw = () => {
    if (!document.body.classList.contains('bg-pattern-synapse')) { removeEventListener('resize', onR); canvas.remove(); return; }
    requestAnimationFrame(draw); ctx.clearRect(0, 0, W, H); const c = _effColor();
    if (pulses.length < 20 && Math.random() < 0.12) spawn();
    for (let i = pulses.length - 1; i >= 0; i--) {
      const p = pulses[i]; p.x += p.dx; p.y += p.dy;
      if (p.x > W + 12 || p.y > H + 12) { pulses.splice(i, 1); continue; }
      const tx = p.x - (p.dx > 0 ? 12 : 0), ty = p.y - (p.dy > 0 ? 12 : 0);
      const g = ctx.createLinearGradient(tx, ty, p.x, p.y); g.addColorStop(0, 'transparent'); g.addColorStop(1, c);
      ctx.strokeStyle = g; ctx.globalAlpha = 0.35; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(p.x, p.y); ctx.stroke();
      ctx.globalAlpha = 0.55; ctx.fillStyle = c; ctx.beginPath(); ctx.arc(p.x, p.y, 1.2, 0, 7); ctx.fill();
    }
    ctx.globalAlpha = 1;
  };
  draw();
}

function _initRain() {
  const canvas = _mkCanvas('rain-canvas'), ctx = canvas.getContext('2d'), dpr = Math.min(devicePixelRatio || 1, 2);
  let W, H; const drops = [];
  const resize = () => { W = innerWidth; H = innerHeight; canvas.width = W * dpr; canvas.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); };
  resize(); const onR = () => resize(); addEventListener('resize', onR);
  const spawn = () => drops.push({ x: Math.random() * W, y: -40, len: 20 + Math.random() * 40, speed: 4 + Math.random() * 8, alpha: 0.3 + Math.random() * 0.28 });
  const draw = () => {
    if (!document.body.classList.contains('bg-pattern-rain')) { removeEventListener('resize', onR); canvas.remove(); return; }
    requestAnimationFrame(draw); ctx.clearRect(0, 0, W, H); const c = _effColor();
    const inten = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--bg-effect-intensity')) || 1;
    const sm = 0.35 + inten * 0.65, sz = _effSize();
    if (drops.length < 130 * inten && Math.random() < 0.6 * inten) spawn();
    for (let i = drops.length - 1; i >= 0; i--) {
      const d = drops[i]; d.y += d.speed * sm; const eff = d.len * sz;
      if (d.y > H + eff) { drops.splice(i, 1); continue; }
      const g = ctx.createLinearGradient(d.x, d.y - eff, d.x, d.y); g.addColorStop(0, 'transparent'); g.addColorStop(1, c);
      ctx.strokeStyle = g; ctx.globalAlpha = d.alpha; ctx.lineWidth = 1.3 * Math.min(2, Math.max(0.6, sz)); ctx.beginPath(); ctx.moveTo(d.x, d.y - eff); ctx.lineTo(d.x, d.y); ctx.stroke();
    }
    ctx.globalAlpha = 1;
  };
  draw();
}

function _initConstellations() {
  const canvas = _mkCanvas('constellations-canvas'), ctx = canvas.getContext('2d'), dpr = Math.min(devicePixelRatio || 1, 2);
  let W, H, t = 0; let stars = []; const N = 50, DIST = 120;
  const init = () => { stars = []; for (let i = 0; i < N; i++) stars.push({ x: Math.random() * W, y: Math.random() * H, vx: (Math.random() - 0.5) * 0.15, vy: (Math.random() - 0.5) * 0.15, r: 0.8 + Math.random() * 0.8, phase: Math.random() * 7 }); };
  const resize = () => { W = innerWidth; H = innerHeight; canvas.width = W * dpr; canvas.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); init(); };
  resize(); const onR = () => resize(); addEventListener('resize', onR);
  const draw = () => {
    if (!document.body.classList.contains('bg-pattern-constellations')) { removeEventListener('resize', onR); canvas.remove(); return; }
    requestAnimationFrame(draw); t += 0.01; ctx.clearRect(0, 0, W, H); const c = _effColor();
    for (const s of stars) { s.x += s.vx; s.y += s.vy; if (s.x < 0) s.x = W; if (s.x > W) s.x = 0; if (s.y < 0) s.y = H; if (s.y > H) s.y = 0; }
    ctx.strokeStyle = c; ctx.lineWidth = 0.5;
    for (let i = 0; i < stars.length; i++) for (let j = i + 1; j < stars.length; j++) {
      const dx = stars[i].x - stars[j].x, dy = stars[i].y - stars[j].y, d = Math.hypot(dx, dy);
      if (d < DIST) { ctx.globalAlpha = (1 - d / DIST) * 0.15; ctx.beginPath(); ctx.moveTo(stars[i].x, stars[i].y); ctx.lineTo(stars[j].x, stars[j].y); ctx.stroke(); }
    }
    ctx.fillStyle = c;
    for (const s of stars) { const tw = 0.5 + 0.5 * Math.sin(t * 2 + s.phase); ctx.globalAlpha = 0.15 + tw * 0.25; ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, 7); ctx.fill(); }
    ctx.globalAlpha = 1;
  };
  draw();
}

function _initSparkles() {
  const canvas = _mkCanvas('sparkles-canvas'), ctx = canvas.getContext('2d'), dpr = Math.min(devicePixelRatio || 1, 2);
  let W, H; const sp = [];
  const mk = () => ({ x: Math.random() * W, y: Math.random() * H, size: 2 + Math.random() * 5, phase: Math.random() * 7, speed: 0.015 + Math.random() * 0.03, life: 0.5 + Math.random() * 0.5 });
  const resize = () => { W = innerWidth; H = innerHeight; canvas.width = W * dpr; canvas.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); if (!sp.length) for (let i = 0; i < 35; i++) sp.push(mk()); };
  resize(); const onR = () => resize(); addEventListener('resize', onR);
  const star = (x, y, r, c, a) => { ctx.save(); ctx.translate(x, y); ctx.fillStyle = c; ctx.globalAlpha = a; ctx.beginPath(); ctx.moveTo(0, -r); ctx.quadraticCurveTo(r * 0.15, -r * 0.15, r, 0); ctx.quadraticCurveTo(r * 0.15, r * 0.15, 0, r); ctx.quadraticCurveTo(-r * 0.15, r * 0.15, -r, 0); ctx.quadraticCurveTo(-r * 0.15, -r * 0.15, 0, -r); ctx.fill(); ctx.restore(); };
  const draw = () => {
    if (!document.body.classList.contains('bg-pattern-sparkles')) { removeEventListener('resize', onR); canvas.remove(); return; }
    requestAnimationFrame(draw); ctx.clearRect(0, 0, W, H); const c = _effColor(), sz = _effSize();
    sp.forEach(s => { s.phase += s.speed; const tw = Math.sin(s.phase); const a = Math.max(0, tw) * 0.25 * s.life, sc = 0.5 + Math.max(0, tw) * 0.5; if (a > 0.01) star(s.x, s.y, s.size * sc * sz, c, a); if (s.phase > 19) Object.assign(s, mk()); });
    ctx.globalAlpha = 1;
  };
  draw();
}

function _initPetals() {
  const canvas = _mkCanvas('petals-canvas'), ctx = canvas.getContext('2d'), dpr = Math.min(devicePixelRatio || 1, 2);
  let W, H; const pe = [];
  const mk = () => ({ x: Math.random() * W, y: -10 - Math.random() * 40, size: 3 + Math.random() * 5, rot: Math.random() * 7, vr: (Math.random() - 0.5) * 0.03, vy: 0.3 + Math.random() * 0.6, drift: Math.random() * 7, ds: 0.008 + Math.random() * 0.012, wob: 0.3 + Math.random() * 0.8 });
  const resize = () => { W = innerWidth; H = innerHeight; canvas.width = W * dpr; canvas.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); if (!pe.length) for (let i = 0; i < 30; i++) { const p = mk(); p.y = Math.random() * H; pe.push(p); } };
  resize(); const onR = () => resize(); addEventListener('resize', onR);
  const draw = () => {
    if (!document.body.classList.contains('bg-pattern-petals')) { removeEventListener('resize', onR); canvas.remove(); return; }
    requestAnimationFrame(draw); ctx.clearRect(0, 0, W, H); const c = _effColor(), sz = _effSize();
    pe.forEach(p => {
      p.y += p.vy; p.rot += p.vr; p.drift += p.ds; p.x += Math.sin(p.drift) * p.wob;
      if (p.y > H + 15) Object.assign(p, mk());
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot); ctx.fillStyle = c;
      ctx.globalAlpha = 0.2; ctx.beginPath(); ctx.ellipse(-p.size * 0.2 * sz, 0, p.size * 0.6 * sz, p.size * 0.3 * sz, 0.3, 0, 7); ctx.fill();
      ctx.globalAlpha = 0.15; ctx.beginPath(); ctx.ellipse(p.size * 0.2 * sz, 0, p.size * 0.6 * sz, p.size * 0.3 * sz, -0.3, 0, 7); ctx.fill();
      ctx.restore();
    });
    ctx.globalAlpha = 1;
  };
  draw();
}

// shared boilerplate: make a canvas, return {canvas, ctx, get W/H, onResize, alive}
function _fx(id, kls, resetOnResize) {
  const canvas = _mkCanvas(id), ctx = canvas.getContext('2d'), dpr = Math.min(devicePixelRatio || 1, 2);
  const st = { W: 0, H: 0 };
  const resize = () => { st.W = innerWidth; st.H = innerHeight; canvas.width = st.W * dpr; canvas.height = st.H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); resetOnResize && resetOnResize(st); };
  resize(); const onR = () => resize(); addEventListener('resize', onR);
  st.alive = () => { if (document.body.classList.contains('bg-pattern-' + kls)) return true; removeEventListener('resize', onR); canvas.remove(); return false; };
  return { ctx, st };
}

function _initSnow() {
  const { ctx, st } = _fx('snow-canvas', 'snow');
  const flakes = [];
  const mk = () => ({ x: Math.random() * st.W, y: -10, r: 0.8 + Math.random() * 2.6, vy: 0.3 + Math.random() * 1.1, drift: Math.random() * 7, ds: 0.005 + Math.random() * 0.02, sw: 0.4 + Math.random() * 1.2 });
  for (let i = 0; i < 70; i++) { const f = mk(); f.y = Math.random() * st.H; flakes.push(f); }
  const draw = () => {
    if (!st.alive()) return; requestAnimationFrame(draw); ctx.clearRect(0, 0, st.W, st.H);
    const c = _effColor(), sz = _effSize(), inten = _effInten();
    ctx.fillStyle = c;
    while (flakes.length < 70 * inten) flakes.push(mk());
    flakes.forEach(f => {
      f.y += f.vy * (0.5 + inten); f.drift += f.ds; f.x += Math.sin(f.drift) * f.sw;
      if (f.y > st.H + 6) Object.assign(f, mk());
      ctx.globalAlpha = 0.55; ctx.beginPath(); ctx.arc(f.x, f.y, f.r * sz, 0, 7); ctx.fill();
    });
    ctx.globalAlpha = 1;
  };
  draw();
}

function _initEmbers() {
  const { ctx, st } = _fx('embers-canvas', 'embers');
  const em = [];
  const mk = () => ({ x: Math.random() * st.W, y: st.H + 10, r: 0.6 + Math.random() * 1.8, vy: 0.4 + Math.random() * 1.2, drift: Math.random() * 7, ds: 0.01 + Math.random() * 0.03, sw: 0.3 + Math.random() * 0.9, life: 0 });
  for (let i = 0; i < 50; i++) { const e = mk(); e.y = Math.random() * st.H; em.push(e); }
  const draw = () => {
    if (!st.alive()) return; requestAnimationFrame(draw); ctx.clearRect(0, 0, st.W, st.H);
    const c = _effColor(), sz = _effSize(), inten = _effInten();
    while (em.length < 50 * inten) em.push(mk());
    em.forEach(e => {
      e.y -= e.vy * (0.5 + inten); e.drift += e.ds; e.x += Math.sin(e.drift) * e.sw; e.life += 0.01;
      if (e.y < -10) Object.assign(e, mk());
      const tw = 0.4 + 0.6 * Math.abs(Math.sin(e.life * 6));
      ctx.globalAlpha = 0.5 * tw; ctx.fillStyle = c; ctx.beginPath(); ctx.arc(e.x, e.y, e.r * sz, 0, 7); ctx.fill();
    });
    ctx.globalAlpha = 1;
  };
  draw();
}

function _initFireflies() {
  const { ctx, st } = _fx('fireflies-canvas', 'fireflies');
  const fl = [];
  const mk = () => ({ x: Math.random() * st.W, y: Math.random() * st.H, vx: (Math.random() - 0.5) * 0.4, vy: (Math.random() - 0.5) * 0.4, r: 1 + Math.random() * 1.6, phase: Math.random() * 7, speed: 0.01 + Math.random() * 0.03 });
  for (let i = 0; i < 40; i++) fl.push(mk());
  const draw = () => {
    if (!st.alive()) return; requestAnimationFrame(draw); ctx.clearRect(0, 0, st.W, st.H);
    const c = _effColor(), sz = _effSize(), inten = _effInten();
    while (fl.length < 40 * inten) fl.push(mk());
    fl.forEach(f => {
      f.x += f.vx; f.y += f.vy; f.phase += f.speed;
      if (Math.random() < 0.01) { f.vx += (Math.random() - 0.5) * 0.2; f.vy += (Math.random() - 0.5) * 0.2; }
      if (f.x < 0) f.x = st.W; if (f.x > st.W) f.x = 0; if (f.y < 0) f.y = st.H; if (f.y > st.H) f.y = 0;
      const glow = Math.max(0, Math.sin(f.phase));
      if (glow > 0.02) {
        const r = f.r * sz; const g = ctx.createRadialGradient(f.x, f.y, 0, f.x, f.y, r * 5);
        g.addColorStop(0, c); g.addColorStop(1, 'transparent');
        ctx.globalAlpha = 0.25 * glow; ctx.fillStyle = g; ctx.beginPath(); ctx.arc(f.x, f.y, r * 5, 0, 7); ctx.fill();
        ctx.globalAlpha = 0.7 * glow; ctx.fillStyle = c; ctx.beginPath(); ctx.arc(f.x, f.y, r, 0, 7); ctx.fill();
      }
    });
    ctx.globalAlpha = 1;
  };
  draw();
}

function _initBubbles() {
  const { ctx, st } = _fx('bubbles-canvas', 'bubbles');
  const bb = [];
  const mk = () => ({ x: Math.random() * st.W, y: st.H + 20, r: 3 + Math.random() * 14, vy: 0.3 + Math.random() * 1, drift: Math.random() * 7, ds: 0.01 + Math.random() * 0.02, sw: 0.2 + Math.random() * 0.7 });
  for (let i = 0; i < 24; i++) { const b = mk(); b.y = Math.random() * st.H; bb.push(b); }
  const draw = () => {
    if (!st.alive()) return; requestAnimationFrame(draw); ctx.clearRect(0, 0, st.W, st.H);
    const c = _effColor(), sz = _effSize(), inten = _effInten();
    while (bb.length < 24 * inten) bb.push(mk());
    ctx.lineWidth = 1;
    bb.forEach(b => {
      b.y -= b.vy * (0.5 + inten); b.drift += b.ds; b.x += Math.sin(b.drift) * b.sw;
      if (b.y < -25) Object.assign(b, mk());
      const r = b.r * sz;
      ctx.globalAlpha = 0.18; ctx.fillStyle = c; ctx.beginPath(); ctx.arc(b.x, b.y, r, 0, 7); ctx.fill();
      ctx.globalAlpha = 0.4; ctx.strokeStyle = c; ctx.beginPath(); ctx.arc(b.x, b.y, r, 0, 7); ctx.stroke();
      ctx.globalAlpha = 0.5; ctx.beginPath(); ctx.arc(b.x - r * 0.3, b.y - r * 0.3, r * 0.18, 0, 7); ctx.fill();
    });
    ctx.globalAlpha = 1;
  };
  draw();
}

function _initStarfield() {
  let cx, cy;
  const { ctx, st } = _fx('starfield-canvas', 'starfield', s => { cx = s.W / 2; cy = s.H / 2; });
  const stars = [];
  const mk = () => ({ x: (Math.random() - 0.5) * st.W, y: (Math.random() - 0.5) * st.H, z: Math.random() * st.W, pz: 0 });
  for (let i = 0; i < 240; i++) stars.push(mk());
  const draw = () => {
    if (!st.alive()) return; requestAnimationFrame(draw); ctx.clearRect(0, 0, st.W, st.H);
    const c = _effColor(), sz = _effSize(), inten = _effInten(); const spd = 2 + inten * 8;
    ctx.strokeStyle = c; ctx.fillStyle = c;
    stars.forEach(s => {
      s.pz = s.z; s.z -= spd; if (s.z < 1) { s.x = (Math.random() - 0.5) * st.W; s.y = (Math.random() - 0.5) * st.H; s.z = st.W; s.pz = s.z; }
      const k = 128 / s.z, px = cx + s.x * k, py = cy + s.y * k;
      const pk = 128 / s.pz, ox = cx + s.x * pk, oy = cy + s.y * pk;
      const a = Math.min(1, (1 - s.z / st.W) * 1.2);
      ctx.globalAlpha = 0.6 * a; ctx.lineWidth = Math.max(0.5, (1 - s.z / st.W) * 2 * sz);
      ctx.beginPath(); ctx.moveTo(ox, oy); ctx.lineTo(px, py); ctx.stroke();
    });
    ctx.globalAlpha = 1;
  };
  draw();
}

function _initMatrix() {
  let cols, drops;
  const FS = 14;
  const { ctx, st } = _fx('matrix-canvas', 'matrix', s => { cols = Math.ceil(s.W / FS); drops = Array.from({ length: cols }, () => Math.random() * -40); });
  const glyph = () => String.fromCharCode(0x30a0 + Math.floor(Math.random() * 96));
  let frame = 0;
  const draw = () => {
    if (!st.alive()) return; requestAnimationFrame(draw);
    const inten = _effInten();
    // trail fade — overdraw bg translucently instead of a hard clear
    const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#000';
    ctx.globalAlpha = 0.08; ctx.fillStyle = bg; ctx.fillRect(0, 0, st.W, st.H); ctx.globalAlpha = 1;
    if ((frame++ % Math.max(1, Math.round(2 / (0.4 + inten)))) !== 0) return;
    const c = _effColor(); ctx.font = FS + "px 'JetBrains Mono', monospace";
    for (let i = 0; i < cols; i++) {
      const x = i * FS, y = drops[i] * FS;
      ctx.globalAlpha = 0.9; ctx.fillStyle = c; ctx.fillText(glyph(), x, y);
      if (y > st.H && Math.random() > 0.975) drops[i] = 0; else drops[i]++;
    }
    ctx.globalAlpha = 1;
  };
  draw();
}

function _initAurora() {
  const { ctx, st } = _fx('aurora-canvas', 'aurora');
  let t = 0;
  const draw = () => {
    if (!st.alive()) return; requestAnimationFrame(draw); ctx.clearRect(0, 0, st.W, st.H);
    t += 0.004 * (0.4 + _effInten()); const c = _effColor(), sz = _effSize();
    for (let b = 0; b < 3; b++) {
      const baseY = st.H * (0.3 + b * 0.18); const amp = (40 + b * 30) * sz;
      ctx.beginPath(); ctx.moveTo(0, st.H);
      for (let x = 0; x <= st.W; x += 16) {
        const y = baseY + Math.sin(x * 0.004 + t * (1 + b * 0.4) + b) * amp + Math.sin(x * 0.011 - t * 2) * amp * 0.4;
        ctx.lineTo(x, y);
      }
      ctx.lineTo(st.W, st.H); ctx.closePath();
      const g = ctx.createLinearGradient(0, baseY - amp, 0, st.H);
      g.addColorStop(0, c); g.addColorStop(1, 'transparent');
      ctx.globalAlpha = 0.12; ctx.fillStyle = g; ctx.fill();
    }
    ctx.globalAlpha = 1;
  };
  draw();
}

function _initWaves() {
  const { ctx, st } = _fx('waves-canvas', 'waves');
  let t = 0;
  const draw = () => {
    if (!st.alive()) return; requestAnimationFrame(draw); ctx.clearRect(0, 0, st.W, st.H);
    t += 0.02 * (0.4 + _effInten()); const c = _effColor(), sz = _effSize();
    ctx.strokeStyle = c; ctx.lineWidth = 1;
    for (let line = 0; line < 5; line++) {
      const baseY = st.H * (0.2 + line * 0.15); const amp = (18 + line * 8) * sz;
      ctx.globalAlpha = 0.1 + line * 0.04; ctx.beginPath();
      for (let x = 0; x <= st.W; x += 10) {
        const y = baseY + Math.sin(x * 0.012 + t + line * 0.7) * amp;
        x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  };
  draw();
}

// ── editor (modal OR inline) ───────────────────────────────────────────────────
let _draft = null;
let _editorRoot = null;        // where the editor paints: the modal #theme-editor or an inline el
let _editorInline = false;     // inline drops the overlay/close/done chrome + folds dark/light into 'default'
let _onEditorChange = null;    // settings.js hook — refresh the lock state on every commit
const PATTERNS = ['none', 'dots', 'grid', 'crosshatch', 'scanlines', 'synapse', 'rain', 'snow', 'embers',
  'fireflies', 'bubbles', 'starfield', 'constellations', 'sparkles', 'petals', 'matrix', 'aurora', 'waves'];
// patterns with no tunable color/intensity (pure CSS) — hide the effect controls for these
const NO_FX = new Set(['none', 'dots', 'grid', 'crosshatch', 'scanlines']);
const BASE_LABELS = [['bg', 'background'], ['text', 'text'], ['panel', 'panel'], ['faint', 'border'], ['accent', 'accent']];

// the two base presets ARE the "default theme" (its dark + light modes); the editor's
// preset grid treats everything else as a real preset.
export const BASE_PRESETS = ['dark', 'light'];
export const isBasePreset = n => BASE_PRESETS.includes(n);

function _commit() { applyAppearance(_draft); save(_draft); _onEditorChange && _onEditorChange(_draft); }

// ── public appearance API (used by the settings "default theme" controls) ───────
export function getAppearance() { return loadLocal(); }

// the "default theme" controls (light/dark buttons AND the default preset tile) are a clean
// slate / escape hatch from a fancy preset: keep only the base light/dark feel + the current
// accent (and saved custom themes), and reset EVERYTHING else — font, density, pattern,
// frosted glass, bg effect — back to defaults.
export function resetToDefault(mode) {
  const a = loadLocal();
  const base = mode === 'light' ? PRESETS.light : PRESETS.dark;
  const accent = a.colors && a.colors.accent;
  const d = DEFAULT();
  d.preset = mode === 'light' ? 'light' : 'dark';
  d.colors = { ...base.colors, accent: accent || base.colors.accent };
  d.customThemes = a.customThemes || {};
  applyAppearance(d); save(d);
  return d;
}

// override just the accent (''/null restores the active preset's own accent). writes into
// the appearance object so it survives reload (the old aide-accent path was clobbered by it).
export function setAccent(hex) {
  const a = loadLocal();
  a.colors = { ...(a.colors || PRESETS.dark.colors) };
  if (hex) a.colors.accent = hex;
  else { const base = PRESETS[a.preset] || PRESETS.dark; a.colors.accent = base.colors.accent; }
  applyAppearance(a); save(a);
  return a;
}

// render the editor inline into `el` (no modal chrome). opts.onChange fires after each commit.
export function renderThemeEditorInto(el, opts = {}) {
  if (!el) return;
  _draft = loadLocal();
  _editorRoot = el; _editorInline = true; _onEditorChange = opts.onChange || null;
  el.classList.add('te-inline-editor');
  _renderEditor();
}

export function openThemeEditor() {
  _draft = loadLocal();
  _editorInline = false; _onEditorChange = null;
  document.getElementById('theme-editor-overlay')?.remove();
  const ov = document.createElement('div');
  ov.id = 'theme-editor-overlay';
  ov.className = 'te-overlay';
  ov.innerHTML = '<div class="te-modal" id="theme-editor"></div>';
  document.body.appendChild(ov);
  ov.addEventListener('mousedown', e => { if (e.target === ov) _close(); });
  _editorRoot = document.getElementById('theme-editor');
  _renderEditor();
}
function _close() { document.getElementById('theme-editor-overlay')?.remove(); }

function esc(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

function _swatch(name, c) {
  return `<button class="te-preset${_draft.preset === name ? ' active' : ''}" data-preset="${name}" title="${name}">
    <span class="te-preset-quad"><i style="background:${c.bg}"></i><i style="background:${c.panel}"></i><i style="background:${c.accent}"></i><i style="background:${c.text}"></i></span>
    <span class="te-preset-name">${name}</span></button>`;
}

function _seg(field, opts) {
  return `<div class="te-seg" data-seg="${field}">${opts.map(o => `<button class="te-seg-opt${_draft[field] === o ? ' active' : ''}" data-val="${o}">${o}</button>`).join('')}</div>`;
}

// the inline preset grid hides dark/light (they're the "default theme") and leads with a
// single "default" tile that drops you back onto the base theme.
function _defaultTile() {
  const active = isBasePreset(_draft.preset);
  return `<button class="te-preset${active ? ' active' : ''}" data-preset="default" title="default">
    <span class="te-preset-quad"><i style="background:#0a0a0a"></i><i style="background:#f5f4f1"></i><i style="background:var(--accent)"></i><i style="background:#e8e6e3"></i></span>
    <span class="te-preset-name">default</span></button>`;
}
function _presetGridHtml() {
  if (_editorInline) {
    return _defaultTile() + Object.entries(PRESETS).filter(([n]) => !isBasePreset(n)).map(([n, p]) => _swatch(n, p.colors)).join('');
  }
  return Object.entries(PRESETS).map(([n, p]) => _swatch(n, p.colors)).join('');
}

function _renderEditor() {
  const m = _editorRoot;
  if (!m) return;
  const c = _draft.colors;
  const ct = _draft.customThemes || {};
  const head = _editorInline ? '' : `<div class="te-head"><span class="te-title">theme editor</span><button class="icon-btn" id="te-close" title="close">${window.icon ? window.icon('close') : '×'}</button></div>`;
  const bodyOpen = _editorInline ? '<div class="te-body te-body-inline">' : '<div class="te-body">';
  m.innerHTML = `
    ${head}
    ${bodyOpen}
      <div class="te-sec"><div class="te-sec-h">presets</div><div class="te-presets">${_presetGridHtml()}</div></div>

      <div class="te-sec"><div class="te-sec-h">colors</div><div class="te-colors">
        ${BASE_LABELS.map(([k, label]) => `<label class="te-color"><input type="color" data-color="${k}" value="${esc(c[k])}"><span>${label}</span></label>`).join('')}
      </div></div>

      <div class="te-sec"><div class="te-sec-h">harmony — generate a palette from one color</div><div class="te-harmony">
        <input type="color" id="te-harmony-accent" value="${esc(c.accent)}">
        <div class="te-seg" data-seg="harmony-type">${['complementary', 'analogous', 'triadic', 'monochromatic'].map((o, i) => `<button class="te-seg-opt${i === 0 ? ' active' : ''}" data-val="${o}">${o.slice(0, 4)}</button>`).join('')}</div>
        <div class="te-seg" data-seg="harmony-mode">${['dark', 'light'].map((o, i) => `<button class="te-seg-opt${i === 0 ? ' active' : ''}" data-val="${o}">${o}</button>`).join('')}</div>
        <button class="btn" id="te-harmony-gen">generate</button>
      </div></div>

      <div class="te-row2">
        <div class="te-sec"><div class="te-sec-h">font</div>${_seg('font', ['sans', 'mono', 'serif'])}</div>
        <div class="te-sec"><div class="te-sec-h">density</div>${_seg('density', ['comfortable', 'compact', 'spacious'])}</div>
      </div>

      <div class="te-sec"><div class="te-sec-h">background</div>
        ${_seg('bgPattern', PATTERNS)}
        <div class="te-bg-extra" style="${NO_FX.has(_draft.bgPattern) ? 'display:none' : ''}">
          <label class="te-color te-inline"><input type="color" id="te-effect-color" value="${esc(c.text)}"><span>effect color</span></label>
          <label class="te-slider"><span>intensity</span><input type="range" id="te-intensity" min="0" max="1" step="0.05" value="${_draft.effect?.intensity ?? 1}"></label>
        </div>
        <button class="btn te-toggle-btn${_draft.frosted ? ' primary' : ''}" id="te-frosted">frosted glass: ${_draft.frosted ? 'on' : 'off'}</button>
      </div>

      <div class="te-sec"><div class="te-sec-h">custom themes</div>
        <div class="te-custom-row"><input type="text" id="te-custom-name" class="settings-input" placeholder="name this theme" maxlength="24"><button class="btn primary" id="te-save-custom">save current</button></div>
        <div class="te-custom-list">${Object.keys(ct).length ? Object.keys(ct).map(n => `<span class="te-custom-chip" data-ct="${esc(n)}"><b data-apply="${esc(n)}">${esc(n)}</b><button data-del="${esc(n)}" title="delete">${window.icon ? window.icon('close') : '×'}</button></span>`).join('') : '<span class="te-empty">none saved yet</span>'}</div>
      </div>

      <div class="te-foot">
        <button class="btn" id="te-export">export</button>
        <button class="btn" id="te-import">import</button>
        <button class="btn" id="te-reset">reset to default</button>
        ${_editorInline ? '' : '<button class="btn primary" id="te-done">done</button>'}
      </div>
    </div>`;
  _wireEditor(m);
}

function _wireEditor(m) {
  initColorPickers(m);
  m.querySelector('#te-close')?.addEventListener('click', _close);
  m.querySelector('#te-done')?.addEventListener('click', _close);

  m.querySelectorAll('.te-preset').forEach(b => b.onclick = () => {
    // the synthetic "default" tile drops back onto the base theme, keeping the light/dark
    // feel of whatever you were on + the current accent.
    if (b.dataset.preset === 'default') {
      const a = resetToDefault(_lum(_draft.colors?.bg || '#0a0a0a') > 0.5 ? 'light' : 'dark');
      _draft = a; _onEditorChange && _onEditorChange(_draft); _renderEditor();
      return;
    }
    const p = PRESETS[b.dataset.preset];
    _draft.preset = b.dataset.preset;
    _draft.colors = { ...p.colors };
    // a preset OWNS its background: turn on the one it ships with, else clear any stale
    // pattern from the theme you switched away from (so 'default' etc. land on no bg).
    _draft.bgPattern = p.pattern || 'none';
    _commit(); _renderEditor();
  });

  m.querySelectorAll('input[data-color]').forEach(inp => inp.addEventListener('input', () => {
    _draft.colors[inp.dataset.color] = inp.value;
    _draft.preset = 'custom';
    _commit();
  }));

  m.querySelectorAll('.te-seg[data-seg]').forEach(seg => {
    const field = seg.dataset.seg;
    seg.querySelectorAll('.te-seg-opt').forEach(o => o.onclick = () => {
      seg.querySelectorAll('.te-seg-opt').forEach(x => x.classList.remove('active'));
      o.classList.add('active');
      if (field === 'font' || field === 'density' || field === 'bgPattern') {
        _draft[field] = o.dataset.val;
        _commit();
        if (field === 'bgPattern') {
          const extra = m.querySelector('.te-bg-extra');
          if (extra) extra.style.display = NO_FX.has(o.dataset.val) ? 'none' : '';
        }
      }
    });
  });

  const effC = m.querySelector('#te-effect-color');
  if (effC) effC.addEventListener('input', () => { _draft.effect = { ..._draft.effect, color: effC.value }; _commit(); });
  const inten = m.querySelector('#te-intensity');
  if (inten) inten.addEventListener('input', () => { _draft.effect = { ..._draft.effect, intensity: parseFloat(inten.value) }; _commit(); });
  const fr = m.querySelector('#te-frosted');
  if (fr) fr.addEventListener('click', () => {
    _draft.frosted = !_draft.frosted;
    fr.classList.toggle('primary', _draft.frosted);
    fr.textContent = 'frosted glass: ' + (_draft.frosted ? 'on' : 'off');
    _commit();
  });

  m.querySelector('#te-harmony-gen').onclick = () => {
    const accent = m.querySelector('#te-harmony-accent').value;
    const type = m.querySelector('[data-seg="harmony-type"] .active')?.dataset.val || 'complementary';
    const mode = m.querySelector('[data-seg="harmony-mode"] .active')?.dataset.val || 'dark';
    _draft.colors = generateHarmony(accent, type, mode);
    _draft.preset = 'custom';
    _commit(); _renderEditor();
  };
  m.querySelectorAll('.te-harmony [data-seg] .te-seg-opt').forEach(o => o.onclick = () => {
    o.parentNode.querySelectorAll('.te-seg-opt').forEach(x => x.classList.remove('active'));
    o.classList.add('active');
  });

  m.querySelector('#te-save-custom').onclick = () => {
    const name = m.querySelector('#te-custom-name').value.trim();
    if (!name) { toast('name it first', 'error'); return; }
    if (!_draft.customThemes) _draft.customThemes = {};
    if (Object.keys(_draft.customThemes).length >= 12 && !_draft.customThemes[name]) { toast('12 custom themes max — delete one', 'error'); return; }
    _draft.customThemes[name] = { colors: { ..._draft.colors }, font: _draft.font, density: _draft.density, bgPattern: _draft.bgPattern, frosted: _draft.frosted, effect: { ..._draft.effect } };
    save(_draft); toast(`saved "${name}"`, 'success'); _renderEditor();
  };
  m.querySelectorAll('[data-apply]').forEach(b => b.onclick = () => {
    const t = _draft.customThemes[b.dataset.apply];
    if (t) { _draft = { ..._draft, ...t, colors: { ...t.colors }, preset: b.dataset.apply }; _commit(); _renderEditor(); }
  });
  m.querySelectorAll('[data-del]').forEach(b => b.onclick = () => { delete _draft.customThemes[b.dataset.del]; save(_draft); _renderEditor(); });

  m.querySelector('#te-export').onclick = () => {
    const blob = new Blob([JSON.stringify(_draft, null, 2)], { type: 'application/json' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'alles-theme.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  m.querySelector('#te-import').onclick = () => {
    const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'application/json';
    inp.onchange = () => {
      const f = inp.files[0]; if (!f) return;
      const r = new FileReader();
      r.onload = () => { try { const o = JSON.parse(r.result); if (o && o.colors) { _draft = { ...DEFAULT(), ...o }; _commit(); _renderEditor(); toast('imported', 'success'); } else toast('not a theme file', 'error'); } catch { toast('bad json', 'error'); } };
      r.readAsText(f);
    };
    inp.click();
  };
  m.querySelector('#te-reset').onclick = () => { _draft = DEFAULT(); _commit(); _renderEditor(); };
}

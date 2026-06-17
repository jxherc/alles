// first-run setup wizard — a short, skippable guide: your name → connect a model →
// optional password lock. nothing here is required; "skip setup" bails at any point.
import { toast } from './util.js';
import { addEndpoint } from './models.js';

const PRESETS = [
  { name: 'DeepSeek', url: 'https://api.deepseek.com', key: 'sk-…' },
  { name: 'Anthropic', url: 'https://api.anthropic.com', key: 'sk-ant-…' },
  { name: 'OpenAI', url: 'https://api.openai.com', key: 'sk-…' },
  { name: 'Gemini', url: 'https://generativelanguage.googleapis.com/v1beta/openai', key: 'AIza…' },
  { name: 'Moonshot', url: 'https://api.moonshot.ai', key: 'sk-…' },
  { name: 'Ollama (local)', url: 'http://localhost:11434', key: '' },
];
const STEPS = 3;   // name, model, password (a final "done" panel follows)
let _step = 0, _picked = null;

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

export function openSetupWizard() {
  const m = $('setup-wizard');
  if (!m) return;
  m.style.display = 'flex';
  _step = 0; _picked = null;
  if (!m.dataset.bound) {
    m.dataset.bound = '1';
    $('setup-skip').addEventListener('click', () => _close(true));
    m.addEventListener('click', e => { if (e.target === m) _close(true); });
  }
  _render();
}

function _close(dismiss) {
  const m = $('setup-wizard');
  if (m) m.style.display = 'none';
  if (dismiss) localStorage.setItem('alles-firstrun-dismissed', '1');
  const fr = $('home-firstrun'); if (fr) fr.style.display = 'none';
}

function _dots() {
  const d = $('setup-dots');
  if (d) d.innerHTML = Array.from({ length: STEPS + 1 }, (_, i) =>
    `<span class="setup-dot${i === _step ? ' on' : ''}${i < _step ? ' done' : ''}"></span>`).join('');
}

function _render() {
  _dots();
  const b = $('setup-wizard-body');
  if (!b) return;
  $('setup-skip').style.display = _step >= STEPS ? 'none' : '';
  if (_step === 0) _name(b);
  else if (_step === 1) _model(b);
  else if (_step === 2) _password(b);
  else _done(b);
}

function _name(b) {
  const cur = localStorage.getItem('alles-name') || '';
  b.innerHTML = `
    <div class="setup-title">welcome to alles 👋</div>
    <div class="setup-sub">a quick setup — under a minute. first, what should aide call you?</div>
    <input class="settings-input setup-input" id="sw-name" placeholder="your name (e.g. eric)" value="${esc(cur)}">
    <div class="setup-actions"><span></span><button class="btn primary" id="sw-next">next</button></div>`;
  $('sw-name').focus();
  $('sw-name').addEventListener('keydown', e => { if (e.key === 'Enter') $('sw-next').click(); });
  $('sw-next').addEventListener('click', () => {
    const n = $('sw-name').value.trim();
    if (n) {
      localStorage.setItem('alles-name', n);
      fetch('/api/settings', { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ username: n }) }).catch(() => {});
    }
    _step = 1; _render();
  });
}

function _model(b) {
  b.innerHTML = `
    <div class="setup-title">connect a model</div>
    <div class="setup-sub">paste an API key for a provider, or point at a local Ollama. you can add more later in settings.</div>
    <div class="setup-presets" id="sw-presets">${PRESETS.map((p, i) =>
      `<button class="rule-preset" data-i="${i}">${esc(p.name)}</button>`).join('')}</div>
    <div id="sw-ep" style="display:none">
      <input class="settings-input setup-input" id="sw-url" placeholder="base url">
      <input class="settings-input setup-input" id="sw-key" type="password" placeholder="api key">
    </div>
    <div class="setup-status" id="sw-status"></div>
    <div class="setup-actions"><button class="btn" id="sw-back">back</button>
      <span><button class="btn" id="sw-skip-model">skip for now</button>
      <button class="btn primary" id="sw-add" style="display:none">add + continue</button></span></div>`;
  $('sw-presets').querySelectorAll('.rule-preset').forEach(btn => btn.addEventListener('click', () => {
    _picked = PRESETS[+btn.dataset.i];
    $('sw-presets').querySelectorAll('.rule-preset').forEach(x => x.classList.toggle('sel', x === btn));
    $('sw-ep').style.display = '';
    $('sw-url').value = _picked.url;
    $('sw-key').placeholder = _picked.key || 'leave blank';
    $('sw-key').focus();
    $('sw-add').style.display = '';
  }));
  $('sw-back').addEventListener('click', () => { _step = 0; _render(); });
  $('sw-skip-model').addEventListener('click', () => { _step = 2; _render(); });
  $('sw-add').addEventListener('click', async () => {
    if (!_picked) return;
    const url = $('sw-url').value.trim();
    const key = $('sw-key').value.trim();
    if (!url) { toast('a base url is required', 'error'); return; }
    const btn = $('sw-add'); btn.disabled = true; $('sw-status').textContent = 'connecting…';
    try {
      await addEndpoint(_picked.name, url, key);
      $('sw-status').textContent = '';
      toast(`${_picked.name} connected`, 'success');
      _step = 2; _render();
    } catch (e) {
      $('sw-status').textContent = 'couldn\'t connect — check the key/url (you can also do this later)';
      btn.disabled = false;
    }
  });
}

function _password(b) {
  b.innerHTML = `
    <div class="setup-title">lock alles? <span class="setup-opt">(optional)</span></div>
    <div class="setup-sub">set a password to require it on open. skip if this is just your machine — you can turn it on anytime in alles settings.</div>
    <input class="settings-input setup-input" id="sw-pw" type="password" placeholder="choose a password (min 4 chars)">
    <div class="setup-status" id="sw-status"></div>
    <div class="setup-actions"><button class="btn" id="sw-back">back</button>
      <span><button class="btn" id="sw-skip-pw">skip</button>
      <button class="btn primary" id="sw-enable">enable lock</button></span></div>`;
  $('sw-back').addEventListener('click', () => { _step = 1; _render(); });
  $('sw-skip-pw').addEventListener('click', () => { _step = 3; _render(); });
  $('sw-enable').addEventListener('click', async () => {
    const pw = $('sw-pw').value;
    if (pw.length < 4) { toast('password must be at least 4 characters', 'error'); return; }
    const btn = $('sw-enable'); btn.disabled = true;
    try {
      const r = await fetch('/api/auth/config', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ enabled: true, password: pw }) });
      if (!r.ok) throw new Error();
      toast('password lock on', 'success');
      _step = 3; _render();
    } catch { $('sw-status').textContent = 'could not set the password'; btn.disabled = false; }
  });
}

function _done(b) {
  const name = localStorage.getItem('alles-name') || '';
  b.innerHTML = `
    <div class="setup-title">you're set${name ? `, ${esc(name)}` : ''} 🎉</div>
    <div class="setup-sub">everything else lives in settings whenever you want it. have fun.</div>
    <div class="setup-actions"><span></span><button class="btn primary" id="sw-start">start using alles</button></div>`;
  $('sw-start').addEventListener('click', () => _close(true));
}

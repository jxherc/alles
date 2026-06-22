// cookbook — browse the 900+ model catalog ranked against your actual hardware
// (the hwfit/llmfit engine). discover what fits, at what quant, how fast.
let _built = false;
let _searchTimer = null;

const USE_CASES = ['general', 'coding', 'reasoning', 'chat', 'multimodal', 'embedding', 'image_gen'];
const SORTS = [['score', 'best fit'], ['speed', 'fastest'], ['vram', 'most VRAM'], ['params', 'biggest'], ['newest', 'newest']];
const FIT_LABEL = { perfect: 'perfect', good: 'good', marginal: 'tight', too_tight: "won't fit" };

function esc(s = '') { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
async function cget(url) { const r = await fetch(url); if (!r.ok) throw new Error(r.status); return r.json(); }

export function initCookbook() {
  const body = document.getElementById('cookbook-body');
  if (!body) return;
  if (!_built) {
    body.innerHTML = `
      <div class="cb-controls">
        <input id="cb-search" class="cb-search" placeholder="search models…">
        <select id="cb-usecase" class="cb-sel">${USE_CASES.map(u => `<option value="${u}">${u}</option>`).join('')}</select>
        <select id="cb-sort" class="cb-sel">${SORTS.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select>
        <label class="cb-fitonly"><input type="checkbox" id="cb-fitonly" checked> fits only</label>
        <button class="btn" id="cb-refresh">refresh</button>
      </div>
      <div id="cb-table" class="cb-table"><div class="jrnl-empty">loading catalog…</div></div>`;

    const reload = () => load();
    document.getElementById('cb-usecase').onchange = reload;
    document.getElementById('cb-sort').onchange = reload;
    document.getElementById('cb-fitonly').onchange = reload;
    document.getElementById('cb-refresh').onclick = reload;
    document.getElementById('cb-search').addEventListener('input', () => {
      clearTimeout(_searchTimer); _searchTimer = setTimeout(load, 300);
    });
    _built = true;
  }
  loadHardware();
  load();
}

async function loadHardware() {
  try {
    const s = await cget('/api/local-models/system');
    const gpu = s.has_gpu ? `${s.gpu_name} (${s.gpu_vram_gb}GB)` : 'no GPU';
    const el = document.getElementById('cookbook-hw');
    if (el) el.textContent = `${s.cpu_name || 'cpu'} · ${s.total_ram_gb || '?'}GB RAM · ${gpu} · ${s.backend}`;
  } catch {}
}

async function load() {
  const table = document.getElementById('cb-table');
  if (!table) return;
  const uc = document.getElementById('cb-usecase').value;
  const sort = document.getElementById('cb-sort').value;
  const fitOnly = document.getElementById('cb-fitonly').checked;
  const search = document.getElementById('cb-search').value.trim();
  const qs = new URLSearchParams({ use_case: uc, sort, fit_only: fitOnly, limit: 80 });
  if (search) qs.set('search', search);
  table.innerHTML = '<div class="jrnl-empty">ranking against your hardware…</div>';
  try {
    const d = await cget('/api/local-models/catalog?' + qs);
    if (!d.models.length) { table.innerHTML = '<div class="jrnl-empty">no models match</div>'; return; }
    table.innerHTML = `
      <div class="cb-row cb-head">
        <span>model</span><span>params</span><span>quant</span><span>mode</span>
        <span>VRAM</span><span>speed</span><span>fit</span><span>score</span>
      </div>` + d.models.map(rowHtml).join('');
  } catch (e) {
    table.innerHTML = `<div class="jrnl-empty">catalog failed: ${esc(String(e.message || e))}</div>`;
  }
}

function rowHtml(m) {
  const fit = FIT_LABEL[m.fit_level] || m.fit_level;
  const hf = `https://huggingface.co/${encodeURI(m.name)}`;
  const speed = m.speed_tps ? `${m.speed_tps} t/s` : '—';
  const vram = m.required_gb ? `${m.required_gb} GB` : '—';
  const moe = m.is_moe ? ' <span class="cb-tag">MoE</span>' : '';
  const inst = m.installed ? ' <span class="cb-tag cb-inst">installed</span>' : '';
  return `<div class="cb-row">
    <span class="cb-name"><a href="${hf}" target="_blank" rel="noopener">${esc(m.name)}</a>${moe}${inst}</span>
    <span>${m.params_b}B</span>
    <span class="cb-mono">${esc(m.quant)}</span>
    <span class="cb-mono">${esc((m.run_mode || '').replace('_', ' '))}</span>
    <span>${vram}</span>
    <span>${speed}</span>
    <span class="cb-fit cb-fit-${m.fit_level}">${fit}</span>
    <span class="cb-score">${m.score}</span>
  </div>`;
}

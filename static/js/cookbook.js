// cookbook — browse the 900+ model catalog ranked against your actual hardware
// (the hwfit/llmfit engine). discover what fits, at what quant, how fast.
import { getDropdownValue, populateDropdown } from './dropdown.js?v=213';
import { t } from './i18n.js';
let _built = false;
let _searchTimer = null;
let _loadSequence = 0;

const USE_CASES = ['general', 'coding', 'reasoning', 'chat', 'multimodal', 'embedding', 'image_gen'];
const SORTS = ['score', 'speed', 'vram', 'params', 'newest'];
const useCaseLabel = value => ({
  general: t('cookbook.use_general'), coding: t('cookbook.use_coding'), reasoning: t('cookbook.use_reasoning'), chat: t('cookbook.use_chat'),
  multimodal: t('cookbook.use_multimodal'), embedding: t('cookbook.use_embedding'), image_gen: t('cookbook.use_image_gen'),
})[value];
const sortLabel = value => ({
  score: t('cookbook.sort_score'), speed: t('cookbook.sort_speed'), vram: t('cookbook.sort_vram'),
  params: t('cookbook.sort_params'), newest: t('cookbook.sort_newest'),
})[value];
const fitLabel = level => ({ perfect: t('cookbook.fit_perfect'), good: t('cookbook.fit_good'), marginal: t('cookbook.fit_tight'), too_tight: t('cookbook.fit_wont') })[level];

function esc(s = '') { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
async function cget(url) { const r = await fetch(url); if (!r.ok) throw new Error(r.status); return r.json(); }

export function initCookbook() {
  const body = document.getElementById('cookbook-body');
  if (!body) return;
  if (!_built) {
    body.innerHTML = `
      <div class="cb-controls">
        <input id="cb-search" aria-label="${t('shell.model.search_models_2')}" class="cb-search" placeholder="${t('cookbook.search_placeholder')}">
        <div id="cb-usecase" class="cb-sel custom-select"></div>
        <div id="cb-sort" class="cb-sel custom-select"></div>
        <button type="button" class="cb-fitonly s-switch s-switch-labeled" id="cb-fitonly" role="switch" aria-checked="true">${t('cookbook.fits_only')}</button>
        <button class="btn" id="cb-refresh">${t('common.refresh')}</button>
      </div>
      <div id="cb-table" class="cb-table"><div class="jrnl-empty">${t('cookbook.loading')}</div></div>`;

    labelControls();
    const reload = () => load();
    document.getElementById('cb-usecase').onchange = reload;
    document.getElementById('cb-sort').onchange = reload;
    document.getElementById('cb-fitonly').onclick = event => {
      const button = event.currentTarget;
      button.setAttribute('aria-checked', button.getAttribute('aria-checked') === 'true' ? 'false' : 'true');
      reload();
    };
    document.getElementById('cb-refresh').onclick = reload;
    document.getElementById('cb-search').addEventListener('input', () => {
      _loadSequence++;
      clearTimeout(_searchTimer); _searchTimer = setTimeout(load, 300);
    });
    _built = true;
  }
  loadHardware();
  load();
}

// the controls are built once, so a language switch relabels them in place and keeps the picks
function labelControls() {
  const search = document.getElementById('cb-search');
  const usecase = document.getElementById('cb-usecase');
  const sort = document.getElementById('cb-sort');
  search.setAttribute('aria-label', t('shell.model.search_models_2'));
  search.placeholder = t('cookbook.search_placeholder');
  populateDropdown(usecase, USE_CASES.map(value => ({ value, label: useCaseLabel(value) || value })), getDropdownValue(usecase) || USE_CASES[0]);
  populateDropdown(sort, SORTS.map(value => ({ value, label: sortLabel(value) })), getDropdownValue(sort) || SORTS[0]);
  document.getElementById('cb-fitonly').textContent = t('cookbook.fits_only');
  document.getElementById('cb-refresh').textContent = t('common.refresh');
}

window.addEventListener('alles:localization-change', () => {
  if (!_built) return;
  labelControls();
  loadHardware();
  load();
});

async function loadHardware() {
  try {
    const s = await cget('/api/local-models/system');
    const gpu = s.has_gpu ? `${s.gpu_name} (${s.gpu_vram_gb}GB)` : t('cookbook.no_gpu');
    const el = document.getElementById('cookbook-hw');
    if (el) el.textContent = `${s.cpu_name || t('server.system_cpu')} · ${s.total_ram_gb || '?'}GB RAM · ${gpu} · ${s.backend}`;
  } catch {}
}

async function load() {
  const table = document.getElementById('cb-table');
  if (!table) return;
  const sequence = ++_loadSequence;
  const uc = getDropdownValue(document.getElementById('cb-usecase'));
  const sort = getDropdownValue(document.getElementById('cb-sort'));
  const fitOnly = document.getElementById('cb-fitonly').getAttribute('aria-checked') === 'true';
  const search = document.getElementById('cb-search').value.trim();
  const qs = new URLSearchParams({ use_case: uc, sort, fit_only: fitOnly, limit: 80 });
  if (search) qs.set('search', search);
  table.innerHTML = `<div class="jrnl-empty">${t('cookbook.ranking')}</div>`;
  try {
    const d = await cget('/api/local-models/catalog?' + qs);
    if (sequence !== _loadSequence) return;
    if (!d.models.length) { table.innerHTML = `<div class="jrnl-empty">${t('cookbook.no_match')}</div>`; return; }
    table.innerHTML = `
      <div class="cb-row cb-head">
        <span>${t('aide.bg_model')}</span><span>${t('cookbook.col_params')}</span><span>${t('cookbook.col_quant')}</span><span>${t('shell.settings_themes.mode')}</span>
        <span>${t('cookbook.col_vram')}</span><span>${t('shell.settings_voice.speed')}</span><span>${t('cookbook.col_fit')}</span><span>${t('cookbook.col_score')}</span>
      </div>` + d.models.map(rowHtml).join('');
  } catch (e) {
    if (sequence !== _loadSequence) return;
    table.innerHTML = `<div class="jrnl-empty">${esc(t('cookbook.failed', { message: String(e.message || e) }))}</div>`;
  }
}

function rowHtml(m) {
  const fit = fitLabel(m.fit_level) || m.fit_level;
  const hf = `https://huggingface.co/${encodeURI(m.name)}`;
  const speed = m.speed_tps ? `${m.speed_tps} t/s` : '—';
  const vram = m.required_gb ? `${m.required_gb} GB` : '—';
  const moe = m.is_moe ? ' <span class="cb-tag">MoE</span>' : '';
  const inst = m.installed ? ' <span class="cb-tag cb-inst">' + t('providers.installed') + '</span>' : '';
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

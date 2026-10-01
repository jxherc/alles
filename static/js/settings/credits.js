import { createSettingsPane } from './pane.js';
import { t, tp } from '../i18n.js';
import { _esc } from './shared.js';

// ── Phase 10 manifest-driven Credits ─────────────────────────────────────────
let _creditsManifest = null;
let _creditsCategory = 'all';
let _creditsQuery = '';
let _creditsSelectedId = '';
let _creditsBusy = false;
let _creditsLoadGeneration = 0;
const _creditDetails = new Map();
const _creditDetailLoads = new Map();
let _creditDetailGeneration = 0;

function _visibleCredits() {
  const query = _creditsQuery.trim().toLowerCase();
  return (_creditsManifest?.entries || []).filter(entry => {
    const categoryMatches = _creditsCategory === 'all' || entry.category === _creditsCategory;
    const queryMatches = !query || [entry.name, entry.summary, entry.version, entry.license]
      .some(value => String(value || '').toLowerCase().includes(query));
    return categoryMatches && queryMatches;
  });
}

function _renderCreditDetail(entry) {
  const detail = document.getElementById('credits-detail');
  if (!detail) return;
  if (!entry) {
    detail.innerHTML = `<p>${_esc(t('credits.no_match'))}</p>`;
    return;
  }
  const licenseTexts = entry.license_texts || [];
  const noticeTexts = entry.notice_texts || [];
  const localText = [...licenseTexts, ...noticeTexts];
  detail.innerHTML = `
    <h3>${_esc(entry.name)}</h3>
    <p>${_esc(entry.summary)}</p>
    <dl>
      <div><dt>${_esc(t('credits.field.category'))}</dt><dd>${_esc(t(`credits.category.${entry.category}`))}</dd></div>
      <div><dt>${_esc(t('credits.field.version'))}</dt><dd dir="ltr">${_esc(entry.version)}</dd></div>
      <div><dt>${_esc(t('credits.field.license'))}</dt><dd>${_esc(entry.license)}</dd></div>
      <div><dt>${_esc(t('credits.field.local_text'))}</dt><dd>${localText.length ? _esc(tp('credits.local_file_count', localText.length)) : _esc(t('credits.not_recorded'))}</dd></div>
    </dl>
    <a class="credits-source" href="${_esc(entry.source_url)}" target="_blank" rel="noreferrer">${_esc(t('credits.open_source'))}</a>
    ${localText.map(item => `
      <details class="credits-license">
        <summary>${_esc(item.name)}</summary>
        <pre dir="ltr">${_esc(item.text)}</pre>
      </details>
    `).join('')}
  `;
}

async function _loadCreditDetail(entry) {
  const detail = document.getElementById('credits-detail');
  const generation = ++_creditDetailGeneration;
  if (!detail || !entry) {
    _renderCreditDetail(null);
    return;
  }
  const cached = _creditDetails.get(entry.id);
  if (cached) {
    _renderCreditDetail(cached);
    return;
  }
  detail.innerHTML = `<p>${_esc(t('credits.detail_loading'))}</p>`;
  let pending = _creditDetailLoads.get(entry.id);
  if (!pending) {
    pending = fetch(`/api/credits/${encodeURIComponent(entry.id)}`).then(async response => {
      if (!response.ok) throw new Error(t('credits.detail_error'));
      const value = await response.json();
      if (_creditDetailLoads.get(entry.id) === pending) _creditDetails.set(entry.id, value);
      return value;
    }).finally(() => {
      if (_creditDetailLoads.get(entry.id) === pending) _creditDetailLoads.delete(entry.id);
    });
    _creditDetailLoads.set(entry.id, pending);
  }
  try {
    const value = await pending;
    if (generation !== _creditDetailGeneration || _creditsSelectedId !== entry.id) return;
    _renderCreditDetail(value);
  } catch (error) {
    if (generation !== _creditDetailGeneration || _creditsSelectedId !== entry.id) return;
    detail.innerHTML = `
      <p>${_esc(error.message || t('credits.detail_error'))}</p>
      <button type="button" data-credit-detail-retry="${_esc(entry.id)}">${_esc(t('common.retry'))}</button>
    `;
  }
}

function _renderCredits() {
  const list = document.getElementById('credits-list');
  const summary = document.getElementById('credits-summary');
  const coverage = document.getElementById('credits-coverage');
  if (!list || !summary || !coverage || !_creditsManifest) return;
  const entries = _visibleCredits();
  if (!entries.some(entry => entry.id === _creditsSelectedId)) _creditsSelectedId = entries[0]?.id || '';
  list.innerHTML = entries.length ? entries.map(entry => `
    <button class="credits-row" type="button" data-credit-id="${_esc(entry.id)}" aria-current="${entry.id === _creditsSelectedId ? 'true' : 'false'}">
      <span><strong>${_esc(entry.name)}</strong><small>${_esc(entry.summary)}</small></span>
      <em>${_esc(entry.license)}</em>
    </button>
  `).join('') : `<div class="credits-empty">${_esc(t('credits.no_match'))}</div>`;
  const inventoryState = _creditsManifest.coverage?.complete
    ? t('credits.inventory.complete')
    : t('credits.inventory.in_progress');
  summary.textContent = `${tp('credits.entry_shown', entries.length)} · ${inventoryState}`;
  const gapCount = Number(_creditsManifest.coverage?.gap_count || 0);
  coverage.textContent = _creditsManifest.coverage?.complete
    ? t('credits.coverage_complete')
    : `${t('credits.inventory.in_progress')} · ${tp('credits.gap_remaining', gapCount)}`;
  void _loadCreditDetail(entries.find(entry => entry.id === _creditsSelectedId));
}

function _setCreditsBusy(busy) {
  _creditsBusy = busy;
  const workbench = document.getElementById('credits-settings-workbench');
  if (workbench) {
    workbench.inert = busy;
    workbench.setAttribute('aria-busy', String(busy));
  }
}

async function loadCreditsPane(isCurrent = () => true) {
  const loadState = document.getElementById('credits-settings-load-state');
  const coverage = document.getElementById('credits-coverage');
  if (!loadState || _creditsBusy) return;
  const generation = ++_creditsLoadGeneration;
  _setCreditsBusy(true);
  loadState.textContent = t('credits.loading');
  try {
    const response = await fetch('/api/credits');
    if (!response.ok) throw new Error(t('credits.load_error'));
    const manifest = await response.json();
    if (generation !== _creditsLoadGeneration || !isCurrent()) return;
    _creditsManifest = manifest;
    _creditDetails.clear();
    _creditDetailLoads.clear();
    _renderCredits();
    loadState.textContent = _creditsManifest.coverage?.complete
      ? t('credits.inventory.complete')
      : t('credits.inventory.in_progress');
  } catch (error) {
    if (generation !== _creditsLoadGeneration || !isCurrent()) return;
    loadState.textContent = t('credits.unavailable');
    if (coverage) coverage.innerHTML = `${_esc(error.message || t('credits.load_error'))} <button type="button" data-credits-retry>${_esc(t('common.retry'))}</button>`;
  } finally {
    if (generation === _creditsLoadGeneration) _setCreditsBusy(false);
  }
}

function _selectCreditsCategory(button) {
  const tabs = [...document.querySelectorAll('[data-credit-category]')];
  tabs.forEach(tab => {
    const selected = tab === button;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  _creditsCategory = button.dataset.creditCategory;
  _renderCredits();
}

function _wireCreditsPane() {
  const pane = document.getElementById('s-pane-credits');
  if (!pane || pane.dataset.creditsBound) return;
  pane.dataset.creditsBound = '1';
  pane.addEventListener('click', event => {
    const tab = event.target.closest('[data-credit-category]');
    if (tab) {
      _selectCreditsCategory(tab);
      return;
    }
    const row = event.target.closest('[data-credit-id]');
    if (row) {
      _creditsSelectedId = row.dataset.creditId;
      _renderCredits();
      requestAnimationFrame(() => {
        document.querySelector(`[data-credit-id="${CSS.escape(_creditsSelectedId)}"]`)?.focus({ preventScroll: true });
      });
      return;
    }
    if (event.target.closest('[data-credits-retry]')) loadCreditsPane();
    const detailRetry = event.target.closest('[data-credit-detail-retry]');
    if (detailRetry) {
      const entry = (_creditsManifest?.entries || []).find(item => item.id === detailRetry.dataset.creditDetailRetry);
      if (entry) void _loadCreditDetail(entry);
    }
  });
  pane.addEventListener('keydown', event => {
    const tab = event.target.closest('[data-credit-category]');
    if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...pane.querySelectorAll('[data-credit-category]')];
    const index = tabs.indexOf(tab);
    let next = index;
    if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    _selectCreditsCategory(tabs[next]);
    tabs[next].focus();
  });
  document.getElementById('credits-search')?.addEventListener('input', event => {
    _creditsQuery = event.target.value;
    _renderCredits();
  });
}


export const creditsPane = createSettingsPane({
  init: _wireCreditsPane,
  load: loadCreditsPane,
  dispose() {
    _creditsLoadGeneration += 1;
    _creditDetailGeneration += 1;
    _creditDetailLoads.clear();
    _setCreditsBusy(false);
  },
});

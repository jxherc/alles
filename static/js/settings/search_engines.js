// Settings → search: custom engines. Which engine answers, and its key, live in the andromeda section.
// The list comes from /api/search/engines, so a new engine needs no change here.
import { _esc } from './shared.js';
import { toast, plainError } from '../util.js';
import { t } from '../i18n.js';
import { confirm as _dlgConfirm } from '../dialog.js';
import { wireChoiceGroup } from '../kokuen.js?v=4';

let _engines = [];
let _editing = null; // custom engine id being edited, '' for a new one

const $ = id => document.getElementById(id);
const engineById = id => _engines.find(engine => engine.id === id);
// the server calls its keyless engine "free search" in english
const engineName = engine => engine.id === 'duckduckgo' ? t('andromeda.x_free_search') : engine.label;

async function _json(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data?.error?.message || data?.detail || t('settings.search_request_failed', { status: response.status }));
  return data;
}

export async function loadSearchEngines() {
  _engines = (await _json('/api/search/engines')).engines || [];
  renderCustomList();
}

// ── custom engines ──
function renderCustomList() {
  const list = $('s-custom-search-list');
  if (!list) return;
  const rows = _engines.filter(engine => engine.custom);
  list.innerHTML = rows.length ? rows.map(engine => `
    <div class="settings-list-row" data-custom-engine="${_esc(engine.id)}">
      <div style="min-width:0;flex:1">
        <div class="row-name">${_esc(engineName(engine))}</div>
        <div class="row-meta">${_esc(engine.url)}${engine.key_configured ? ` · ${_esc(t('settings.search_key_saved'))}` : ''}</div>
      </div>
      <button type="button" class="btn" data-custom-edit="${_esc(engine.id)}">${_esc(t('common.edit'))}</button>
      <button type="button" class="btn" data-custom-remove="${_esc(engine.id)}">${_esc(t('common.remove'))}</button>
    </div>`).join('') : `<div class="s-card-hint">${_esc(t('settings.search_no_custom'))}</div>`;
}

const FORM_FIELDS = {
  name: 's-cse-name', url: 's-cse-url', body: 's-cse-body', key_header: 's-cse-key-header',
  key_prefix: 's-cse-key-prefix', results: 's-cse-results', url_field: 's-cse-url-field',
  title_field: 's-cse-title-field', snippet_field: 's-cse-snippet-field',
};

function setMethod(value) {
  $('s-cse-method').querySelectorAll('[role="radio"]').forEach(choice => {
    const on = choice.dataset.value === value;
    choice.setAttribute('aria-checked', String(on));
    choice.tabIndex = on ? 0 : -1;
  });
  $('s-cse-body-row').hidden = value !== 'POST';
}

const currentMethod = () => $('s-cse-method').querySelector('[aria-checked="true"]')?.dataset.value || 'GET';

function openForm(engine = null) {
  _editing = engine?.id || '';
  const form = $('s-custom-search-form');
  for (const [field, id] of Object.entries(FORM_FIELDS)) {
    const saved = field === 'name' ? engine?.label : engine?.[field];
    $(id).value = engine ? saved || '' : { url_field: 'url', title_field: 'title', snippet_field: 'snippet' }[field] || '';
  }
  $('s-cse-key').value = '';
  $('s-cse-key').placeholder = engine?.key_configured ? t('settings.search_key_saved_placeholder') : '';
  setMethod(engine?.method || 'GET');
  $('s-cse-status').textContent = '';
  $('s-cse-save').textContent = engine ? t('settings.save_changes') : t('settings.search_save_engine');
  form.hidden = false;
  $('s-custom-search-add').hidden = true;
  $('s-cse-name').focus();
}

function closeForm() {
  _editing = null;
  $('s-custom-search-form').hidden = true;
  $('s-custom-search-add').hidden = false;
  $('s-custom-search-add').focus();
}

async function saveCustom(event) {
  event.preventDefault();
  const button = $('s-cse-save');
  const status = $('s-cse-status');
  const body = { method: currentMethod() };
  for (const [field, id] of Object.entries(FORM_FIELDS)) body[field] = $(id).value.trim();
  const key = $('s-cse-key').value.trim();
  body.key = key || (_editing ? null : '');
  button.disabled = true;
  status.dataset.state = '';
  status.textContent = t('common.saving');
  try {
    const url = _editing ? `/api/search/custom/${encodeURIComponent(_editing)}` : '/api/search/custom';
    const saved = await _json(url, {
      method: _editing ? 'PUT' : 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
    });
    await loadSearchEngines();
    toast(t('settings.search_engine_saved', { name: saved.label }), 'success');
    closeForm();
  } catch (error) {
    status.textContent = plainError(error.message || t('settings.search_engine_save_failed'));
    status.dataset.state = 'error';
  } finally {
    button.disabled = false;
  }
}

async function removeCustom(id) {
  const engine = engineById(id);
  if (!engine || !await _dlgConfirm(t('settings.search_remove_confirm', { name: engine.label }), { confirmLabel: t('settings.search_remove_engine') })) return;
  try {
    await _json(`/api/search/custom/${encodeURIComponent(id)}`, { method: 'DELETE' });
    await loadSearchEngines();
    toast(t('settings.search_engine_removed', { name: engine.label }), 'success');
  } catch (error) {
    toast(error.message || t('settings.search_engine_remove_failed'), 'error');
  }
}

export function wireSearchEngines() {
  $('s-custom-search-add')?.addEventListener('click', () => openForm());
  $('s-cse-cancel')?.addEventListener('click', closeForm);
  $('s-custom-search-form')?.addEventListener('submit', saveCustom);
  $('s-custom-search-form')?.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); closeForm(); }
  });
  const method = $('s-cse-method');
  if (method) {
    method.addEventListener('click', event => {
      const choice = event.target.closest('[role="radio"]');
      if (choice) setMethod(choice.dataset.value);
    });
    wireChoiceGroup(method);
  }
  $('s-custom-search-list')?.addEventListener('click', event => {
    const edit = event.target.closest('[data-custom-edit]');
    const remove = event.target.closest('[data-custom-remove]');
    if (edit) openForm(engineById(edit.dataset.customEdit));
    if (remove) removeCustom(remove.dataset.customRemove);
  });
}

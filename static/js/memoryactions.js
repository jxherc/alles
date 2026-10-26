import { t, tp } from './i18n.js';

function safe(value = '') {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export function provenanceLabels(provenance = {}) {
  const labels = [];
  if (provenance.owner_instructions) labels.push(t('aide.prov_owner_instructions'));
  if (provenance.project_instructions) labels.push(t('aide.prov_project_instructions'));
  if (provenance.persona?.name) labels.push(t('aide.prov_persona', { name: provenance.persona.name }));
  const count = Array.isArray(provenance.memories) ? provenance.memories.length : 0;
  if (count) labels.push(tp('aide.prov_memories', count));
  if (provenance.document?.path) labels.push(t('aide.prov_note', { path: provenance.document.path }));
  if (Array.isArray(provenance.document?.documents)) labels.push(tp('aide.prov_selected_notes', provenance.document.documents.length));
  if (provenance.model) labels.push(`${provenance.endpoint || t('aide.prov_model')} / ${provenance.model}`);
  return labels;
}

// "global memory", not "global · id 87317e08-…": the id means nothing to read. it stays on the
// row's data-memory-id and its forget button
export function memoryProvenanceLabel(memory = {}) {
  const scope = String(memory.scope || '').trim() || 'global';
  return t('aide.prov_scope_memory', { scope });
}

export function contextProvenanceElement(provenance = {}) {
  const labels = provenanceLabels(provenance);
  if (!labels.length) return null;
  const details = document.createElement('details');
  details.className = 'context-provenance';
  details.dataset.labels = labels.join(' · ');
  const memories = Array.isArray(provenance.memories) ? provenance.memories : [];
  details.innerHTML = `
    <summary>${safe(t('aide.prov_context', { labels: labels.join(' · ') }))}</summary>
    <div class="context-provenance-body">
      ${provenance.owner_instructions ? `<div>${safe(t('aide.prov_owner_used'))}</div>` : ''}
      ${provenance.project_instructions ? `<div>${safe(t('aide.prov_project_used'))}</div>` : ''}
      ${provenance.persona?.name ? `<div>${safe(t('aide.prov_persona', { name: provenance.persona.name }))}</div>` : ''}
      ${provenance.document?.path ? `<div>${safe(t('aide.prov_note_used', { path: provenance.document.path }))}</div>` : ''}
      ${memories.map(memory => `<div class="context-memory" data-memory-id="${safe(memory.id)}">
        <span><b>${safe(memoryProvenanceLabel(memory))}</b> · ${safe(memory.text || '')}</span>
        <button class="act-btn" type="button" data-forget-memory="${safe(memory.id)}">${safe(t('aide.prov_forget'))}</button>
      </div>`).join('')}
      ${provenance.model ? `<div>${safe(t('aide.prov_model_line', { model: `${provenance.endpoint || ''} / ${provenance.model}` }))}</div>` : ''}
    </div>`;
  details.querySelectorAll('[data-forget-memory]').forEach(button => {
    button.addEventListener('click', () => forgetResponseMemory(button, button.dataset.forgetMemory));
  });
  for (const source of provenance.document?.documents || []) {
    const snapshot = document.createElement('details');
    snapshot.className = 'source-snapshot';
    const label = document.createElement('summary'); label.textContent = source.path;
    const note = document.createElement('p'); note.textContent = t('aide.prov_version_used');
    const open = document.createElement('a'); open.textContent = t('aide.prov_open_source');
    open.href = `/?app=docs&doc=${encodeURIComponent(source.path)}&doc_hash=${encodeURIComponent(source.hash)}`;
    const content = document.createElement('pre'); content.textContent = source.content;
    content.tabIndex = 0; content.setAttribute('aria-label', t('aide.prov_source_text', { path: source.path }));
    snapshot.append(label, note, open, content);
    details.querySelector('.context-provenance-body').append(snapshot);
  }
  return details;
}

export function sourceCitationStatus(report) {
  if (!report) return null;
  const status = document.createElement('p'); status.className = 'source-citation-status';
  status.textContent = report.status === 'cited' ? t('aide.cite_cited')
    : report.status === 'needs_review' ? t('aide.cite_needs_review')
      : t('aide.cite_none');
  return status;
}

export async function forgetResponseMemory(button, memoryId) {
  if (!memoryId || button.disabled) return;
  button.disabled = true;
  const response = await fetch(`/api/memories/${encodeURIComponent(memoryId)}`, { method: 'DELETE' })
    .catch(() => null);
  if (!response?.ok) {
    button.disabled = false;
    button.textContent = t('aide.prov_forget_failed');
    return;
  }
  const row = button.closest('.context-memory');
  if (row) row.innerHTML = `<span>${safe(t('aide.prov_forgotten'))}</span>`;
}

export async function rememberUserMessage(button) {
  const row = button?.closest('.msg-row');
  const text = row?.querySelector('.user-bubble')?.textContent?.trim();
  if (!text || button.disabled) return;
  // disabling drops focus to the page; only take it back if nothing else has it by then
  const lost = () => !document.activeElement || document.activeElement === document.body || document.activeElement === button;
  button.disabled = true;
  const projectId = window._currentSession?.project_id || '';
  const response = await fetch('/api/memories', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      text,
      scope: projectId ? 'project' : 'global',
      project_id: projectId,
    }),
  }).catch(() => null);
  const memory = await response?.json().catch(() => ({}));
  if (!response?.ok) {
    button.disabled = false;
    button.textContent = memory?.detail || t('aide.remember_failed');
    if (lost()) button.focus();
    return;
  }
  const status = document.createElement('span');
  status.className = 'memory-confirm';
  status.innerHTML = `${safe(projectId ? t('aide.remembered_project') : t('aide.remembered_global'))} · <button type="button">${safe(t('common.undo'))}</button>`;
  const undo = status.querySelector('button');
  let undoing = false;
  undo.addEventListener('click', async () => {
    if (undoing) return;
    undoing = true;
    const undone = await fetch(`/api/memories/${encodeURIComponent(memory.id)}`, { method: 'DELETE' })
      .catch(() => null);
    undoing = false;
    if (!undone?.ok) return;
    const hadUndo = document.activeElement === undo;
    status.textContent = t('aide.memory_undone');
    // undo is gone with the old text: the receipt itself keeps focus
    if (hadUndo || !document.activeElement || document.activeElement === document.body) {
      status.tabIndex = -1;
      status.focus();
    }
  });
  // the receipt takes the button's place, right under the message
  const refocus = lost();
  button.replaceWith(status);
  if (refocus) undo.focus();
}

if (typeof window !== 'undefined') {
  window.rememberUserMessage = rememberUserMessage;
  window.forgetResponseMemory = forgetResponseMemory;
}

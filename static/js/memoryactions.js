function safe(value = '') {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export function provenanceLabels(provenance = {}) {
  const labels = [];
  if (provenance.owner_instructions) labels.push('owner instructions');
  if (provenance.project_instructions) labels.push('Project instructions');
  if (provenance.persona?.name) labels.push(`persona: ${provenance.persona.name}`);
  const count = Array.isArray(provenance.memories) ? provenance.memories.length : 0;
  if (count) labels.push(`${count} memor${count === 1 ? 'y' : 'ies'}`);
  if (provenance.document?.path) labels.push(`note: ${provenance.document.path}`);
  if (Array.isArray(provenance.document?.documents)) labels.push(`${provenance.document.documents.length} selected notes only`);
  if (provenance.model) labels.push(`${provenance.endpoint || 'model'} / ${provenance.model}`);
  return labels;
}

export function memoryProvenanceLabel(memory = {}) {
  const id = String(memory.id || '').trim() || 'unknown';
  const scope = String(memory.scope || '').trim() || 'global';
  return `${scope} · id ${id}`;
}

export function contextProvenanceElement(provenance = {}) {
  const labels = provenanceLabels(provenance);
  if (!labels.length) return null;
  const details = document.createElement('details');
  details.className = 'context-provenance';
  const memories = Array.isArray(provenance.memories) ? provenance.memories : [];
  details.innerHTML = `
    <summary>context · ${safe(labels.join(' · '))}</summary>
    <div class="context-provenance-body">
      ${provenance.owner_instructions ? '<div>owner instructions used</div>' : ''}
      ${provenance.project_instructions ? '<div>Project instructions used</div>' : ''}
      ${provenance.persona?.name ? `<div>persona: ${safe(provenance.persona.name)}</div>` : ''}
      ${provenance.document?.path ? `<div>note used: ${safe(provenance.document.path)}</div>` : ''}
      ${memories.map(memory => `<div class="context-memory" data-memory-id="${safe(memory.id)}">
        <span><b>${safe(memoryProvenanceLabel(memory))}</b> · ${safe(memory.text || '')}</span>
        <button class="act-btn" type="button" data-forget-memory="${safe(memory.id)}">forget this</button>
      </div>`).join('')}
      ${provenance.model ? `<div>model: ${safe(provenance.endpoint || '')} / ${safe(provenance.model)}</div>` : ''}
    </div>`;
  details.querySelectorAll('[data-forget-memory]').forEach(button => {
    button.addEventListener('click', () => forgetResponseMemory(button, button.dataset.forgetMemory));
  });
  for (const source of provenance.document?.documents || []) {
    const snapshot = document.createElement('details');
    snapshot.className = 'source-snapshot';
    const label = document.createElement('summary'); label.textContent = source.path;
    const note = document.createElement('p'); note.textContent = 'version used for this answer';
    const open = document.createElement('a'); open.textContent = 'open source';
    open.href = `/?app=docs&doc=${encodeURIComponent(source.path)}&doc_hash=${encodeURIComponent(source.hash)}`;
    const content = document.createElement('pre'); content.textContent = source.content;
    content.tabIndex = 0; content.setAttribute('aria-label', `source text: ${source.path}`);
    snapshot.append(label, note, open, content);
    details.querySelector('.context-provenance-body').append(snapshot);
  }
  return details;
}

export function sourceCitationStatus(report) {
  if (!report) return null;
  const status = document.createElement('p'); status.className = 'source-citation-status';
  status.textContent = report.status === 'cited' ? 'source passages included; check that they support the answer'
    : report.status === 'needs_review' ? 'some source references are unavailable; review this answer'
      : 'no source passages cited; review this answer';
  return status;
}

export async function forgetResponseMemory(button, memoryId) {
  if (!memoryId || button.disabled) return;
  button.disabled = true;
  const response = await fetch(`/api/memories/${encodeURIComponent(memoryId)}`, { method: 'DELETE' })
    .catch(() => null);
  if (!response?.ok) {
    button.disabled = false;
    button.textContent = 'forget failed';
    return;
  }
  const row = button.closest('.context-memory');
  if (row) row.innerHTML = '<span>forgotten · no longer used</span>';
}

export async function rememberUserMessage(button) {
  const row = button?.closest('.msg-row');
  const text = row?.querySelector('.user-bubble')?.textContent?.trim();
  if (!text || button.disabled) return;
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
    button.textContent = memory?.detail || 'remember failed';
    return;
  }
  const status = document.createElement('span');
  status.className = 'memory-confirm';
  status.innerHTML = `remembered ${projectId ? 'in Project' : 'globally'} · <button type="button">undo</button>`;
  status.querySelector('button').addEventListener('click', async () => {
    const undone = await fetch(`/api/memories/${encodeURIComponent(memory.id)}`, { method: 'DELETE' })
      .catch(() => null);
    if (undone?.ok) status.textContent = 'memory undone';
  });
  row.querySelector('.user-wrap')?.appendChild(status);
  button.remove();
}

if (typeof window !== 'undefined') {
  window.rememberUserMessage = rememberUserMessage;
  window.forgetResponseMemory = forgetResponseMemory;
}

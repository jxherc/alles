// One stored value per model role. Every screen that edits a role goes through setModelRole,
// then announces it, so the others show the same model without reloading.
import { t } from '../i18n.js';

export const MODEL_ROLES_EVENT = 'alles:model-roles';

const safeLabel = (value = '') => String(value).replace(/[;|]/g, ' ');

async function readSettings() {
  const response = await fetch('/api/settings');
  const settings = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(settings?.detail || t('common.request_failed'));
  return settings;
}

// options for a role picker: automatic, then every model of every connection
export function roleOptions(endpoints, configured) {
  const options = [{ value: '', label: t('common.automatic') }];
  const choices = { '': null };
  let index = 0;
  for (const endpoint of endpoints || []) {
    for (const model of (endpoint.models || [])) {
      const token = `choice-${index++}`;
      options.push({ value: token, label: `${safeLabel(endpoint.name)} · ${safeLabel(model)}` });
      choices[token] = { endpoint_id: endpoint.id, model };
    }
  }
  let selected = '';
  if (configured?.endpoint_id && configured?.model) {
    selected = Object.keys(choices).find(token => {
      const choice = choices[token];
      return choice?.endpoint_id === configured.endpoint_id && choice?.model === configured.model;
    }) || '';
    if (!selected) {
      selected = `unavailable-${index}`;
      options.push({ value: selected, label: t('providers.model_unavailable', { model: safeLabel(configured.model) }) });
      choices[selected] = { endpoint_id: configured.endpoint_id, model: configured.model };
    }
  }
  return { options, choices, selected };
}

export function announceModelRoles(roles, source = '') {
  globalThis.window?.dispatchEvent(new CustomEvent(MODEL_ROLES_EVENT, { detail: { roles, source } }));
}

export function onModelRoles(listener) {
  const handler = event => listener(event.detail || {});
  globalThis.window?.addEventListener(MODEL_ROLES_EVENT, handler);
  return () => globalThis.window?.removeEventListener(MODEL_ROLES_EVENT, handler);
}

// choice is {endpoint_id, model}, or null for automatic. Other roles stay as stored.
export async function setModelRole(role, choice, { source = '' } = {}) {
  const roles = (await readSettings()).model_roles || {};
  const old = roles[role] || {};
  const next = {
    ...roles,
    [role]: choice
      ? { endpoint_id: choice.endpoint_id, model: choice.model, cost_class: old.cost_class || '', fallbacks: old.fallbacks || [] }
      : {},
  };
  const response = await fetch('/api/settings', {
    method: 'PATCH', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ model_roles: next }),
  });
  const saved = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(saved?.detail || t('providers.defaults_not_saved'));
  const stored = saved.model_roles || next;
  announceModelRoles(stored, source);
  return stored;
}

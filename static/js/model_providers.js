// One provider list for settings and first-run setup. Alphabetical; nothing is
// recommended or pre-selected. "custom endpoint" covers anything OpenAI-compatible,
// Anthropic, Gemini or Ollama style that is not listed.
import { t } from './i18n.js';

export const MODEL_PROVIDERS = Object.freeze([
  { id: 'anthropic', label: 'Anthropic', url: 'https://api.anthropic.com', provider: 'anthropic', adapter: 'anthropic' },
  { id: 'cohere', label: 'Cohere', url: 'https://api.cohere.ai', provider: 'custom', adapter: 'openai-compatible' },
  { id: 'deepseek', label: 'DeepSeek', url: 'https://api.deepseek.com', provider: 'deepseek', adapter: 'openai-compatible' },
  { id: 'fireworks', label: 'Fireworks', url: 'https://api.fireworks.ai/inference', provider: 'custom', adapter: 'openai-compatible' },
  { id: 'gemini', label: 'Gemini', url: 'https://generativelanguage.googleapis.com/v1beta/openai', provider: 'gemini', adapter: 'openai-compatible' },
  { id: 'groq', label: 'Groq', url: 'https://api.groq.com/openai', provider: 'custom', adapter: 'openai-compatible' },
  { id: 'kimi', label: 'Kimi', url: 'https://api.moonshot.ai/v1', provider: 'kimi', adapter: 'openai-compatible' },
  { id: 'mistral', label: 'Mistral', url: 'https://api.mistral.ai', provider: 'custom', adapter: 'openai-compatible' },
  { id: 'ollama', label: 'Ollama', get note() { return t('providers.this_machine'); }, url: 'http://localhost:11434', provider: 'ollama', adapter: 'ollama', keyless: true },
  { id: 'openai', label: 'OpenAI', url: 'https://api.openai.com', provider: 'openai', adapter: 'openai-compatible' },
  { id: 'openrouter', label: 'OpenRouter', url: 'https://openrouter.ai/api', provider: 'custom', adapter: 'openai-compatible' },
  { id: 'perplexity', label: 'Perplexity', url: 'https://api.perplexity.ai', provider: 'custom', adapter: 'openai-compatible' },
  { id: 'together', label: 'Together', url: 'https://api.together.xyz', provider: 'custom', adapter: 'openai-compatible' },
  { id: 'xai', label: 'xAI', url: 'https://api.x.ai', provider: 'custom', adapter: 'openai-compatible' },
  { id: 'custom', get label() { return t('providers.custom_endpoint'); }, get note() { return t('providers.any_compatible'); }, url: '', provider: 'custom', adapter: 'openai-compatible', custom: true },
]);

export const API_TYPES = Object.freeze([
  ['openai-compatible', 'OpenAI-compatible'],
  ['anthropic', 'Anthropic'],
  ['gemini', 'Gemini'],
  ['ollama', 'Ollama'],
]);

export const providerById = id => MODEL_PROVIDERS.find(p => p.id === id) || null;

// a blank key is only valid for this machine; the server enforces that too
export function authFor(provider, key) {
  if (key) return 'api_key';
  return provider.keyless || provider.custom ? 'none' : 'api_key';
}

const escHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

// Filterable listbox: type to narrow, arrows move, Enter or click picks.
export function mountProviderPicker(list, { filter = null, selected = '', onPick } = {}) {
  if (!list) return { select() {} };
  list.setAttribute('role', 'listbox');
  let current = selected;
  const options = () => [...list.querySelectorAll('[role="option"]')].filter(o => !o.hidden);
  const render = () => {
    list.innerHTML = MODEL_PROVIDERS.map(p => `
      <button type="button" class="model-provider-option" role="option" data-provider="${p.id}" aria-selected="${p.id === current}" tabindex="-1">
        <span class="model-provider-name">${escHtml(p.label)}</span>${p.note ? `<span class="model-provider-note">${escHtml(p.note)}</span>` : ''}
      </button>`).join('');
    const first = list.querySelector('[aria-selected="true"]') || list.querySelector('[role="option"]');
    if (first) first.tabIndex = 0;
  };
  const select = id => {
    current = id;
    list.querySelectorAll('[role="option"]').forEach(o => o.setAttribute('aria-selected', String(o.dataset.provider === id)));
  };
  render();
  list.addEventListener('click', event => {
    const option = event.target.closest('[role="option"]');
    if (!option) return;
    select(option.dataset.provider);
    onPick?.(providerById(option.dataset.provider));
  });
  list.addEventListener('keydown', event => {
    const items = options();
    const at = items.indexOf(document.activeElement);
    const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
    if (step) {
      event.preventDefault();
      const next = items[Math.max(0, Math.min(items.length - 1, at + step))];
      items.forEach(o => { o.tabIndex = -1; });
      if (next) { next.tabIndex = 0; next.focus(); }
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      const next = event.key === 'Home' ? items[0] : items.at(-1);
      items.forEach(o => { o.tabIndex = -1; });
      if (next) { next.tabIndex = 0; next.focus(); }
    }
  });
  filter?.addEventListener('input', () => {
    const q = filter.value.trim().toLowerCase();
    list.querySelectorAll('[role="option"]').forEach(o => {
      const p = providerById(o.dataset.provider);
      o.hidden = Boolean(q) && !`${p.label} ${p.note || ''}`.toLowerCase().includes(q);
    });
  });
  filter?.addEventListener('keydown', event => {
    if (event.key !== 'ArrowDown') return;
    event.preventDefault();
    const first = options()[0];
    if (first) { first.tabIndex = 0; first.focus(); }
  });
  return { select };
}

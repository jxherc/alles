import { toast } from './util.js';
import { formatDateTime, resolvedTimeZone } from './i18n.js';

let initialized = false;
let state = null;
let editor = null;
let restoreFocus = null;
const savedUrls = new Set();

const root = () => document.getElementById('aide-news-workbench');
const esc = value => String(value ?? '').replace(/[&<>'"]/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
}[character]));

function safeMessage(value) {
  return String(value || 'News is unavailable').replace(/jarvis/gi, 'Jarvis');
}

export function safeNewsUrl(value) {
  try {
    const parsed = new URL(String(value || ''));
    return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : '';
  } catch {
    return '';
  }
}

async function requestJson(url, options = {}, fetcher = fetch) {
  const response = await fetcher(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(safeMessage(payload?.detail || payload?.message));
  return payload;
}

function jsonOptions(method, body) {
  return { method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) };
}

function localZone() {
  return resolvedTimeZone();
}

export function normalizeNewsTimestamp(value) {
  const raw = String(value || '');
  return /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw : `${raw}Z`;
}

function formatWhen(value) {
  if (!value) return 'not yet checked';
  const parsed = new Date(normalizeNewsTimestamp(value));
  if (Number.isNaN(parsed.getTime())) return 'not yet checked';
  return formatDateTime(parsed, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

function switchButton({ checked, label, action, disabled = false, id = '' }) {
  return `<button class="news-switch"${id ? ` id="${id}"` : ''} type="button" role="switch" aria-checked="${checked}" aria-label="${esc(label)}" data-news-action="${action}"${disabled ? ' aria-disabled="true" disabled' : ''}></button>`;
}

function radio(value, selected, label, group) {
  return `<button class="news-choice" type="button" role="radio" aria-checked="${value === selected}" tabindex="${value === selected ? '0' : '-1'}" data-news-radio="${group}" data-value="${esc(value)}">${esc(label)}</button>`;
}

function sourceRow(source) {
  const healthLabel = source.health === 'retry' ? 'retry scheduled' : source.health;
  const healthCopy = source.last_safe_error || (source.last_success_at
    ? `checked ${formatWhen(source.last_success_at)}` : 'nothing fetched yet');
  const priority = source.priority >= 2 ? 'high priority' : source.priority === 0 ? 'low priority' : 'normal priority';
  return `<li class="news-source-row">
    <div class="news-source-name"><strong>${esc(source.name)}</strong><span>${esc(source.category)} · ${esc(source.language)} · ${priority}</span></div>
    <div class="news-source-health" data-health="${esc(source.health)}"><strong>${esc(healthLabel)}</strong><span>${esc(healthCopy)}</span></div>
    <div class="news-source-actions"><button type="button" data-news-edit="${esc(source.id)}">edit</button>${switchButton({ checked: source.enabled, label: `${source.enabled ? 'disable' : 'enable'} ${source.name}`, action: `toggle-source:${source.id}` })}</div>
  </li>`;
}

function briefMarkup(brief) {
  if (!brief) return `<div class="news-preview-empty"><strong>no brief yet</strong><p>Enable News, then run one when you want to check the complete path.</p></div>`;
  const clusters = brief.clusters || [];
  const sourceCount = new Set(clusters.flatMap(cluster => (cluster.links || []).map(link => link.source))).size;
  const cards = clusters.map((cluster, index) => {
    const links = cluster.links || [];
    const first = links.find(link => safeNewsUrl(link.url)) || {};
    const firstUrl = safeNewsUrl(first.url);
    const saved = savedUrls.has(firstUrl);
    return `<article class="news-digest-cluster">
      <h3>${esc(cluster.title)}</h3>
      <p>${esc(cluster.summary)}</p>
      <div class="news-digest-links">${links.map(link => {
        const url = safeNewsUrl(link.url);
        return url
          ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(link.source)}</a>`
          : `<span>${esc(link.source)}</span>`;
      }).join('')}</div>
      ${firstUrl ? `<button type="button" data-news-save="${index}" aria-pressed="${saved}"${saved ? ' disabled' : ''}>${saved ? 'saved to Library' : 'save to Library'}</button>` : ''}
    </article>`;
  }).join('');
  const failures = brief.source_failures || [];
  return `<header class="news-preview-head"><h2>latest brief</h2><span>${clusters.length} cluster${clusters.length === 1 ? '' : 's'} · ${sourceCount} source${sourceCount === 1 ? '' : 's'}</span></header>
    <p class="news-preview-note">${brief.status === 'summary_pending' ? 'Link digest ready. Model summary is pending, so source excerpts remain visible.' : 'Every topic keeps its source links. Nothing enters Library unless you save it.'}</p>
    ${cards || '<div class="news-preview-empty"><strong>no recent stories</strong></div>'}
    ${failures.length ? `<div class="news-digest-warning"><strong>link digest remains available.</strong> ${failures.length} source${failures.length === 1 ? '' : 's'} will retry independently.</div>` : ''}`;
}

function editorMarkup() {
  if (!editor) return '';
  const item = editor.source || {};
  return `<div class="news-editor-backdrop" data-news-editor-backdrop>
    <section class="news-editor" role="dialog" aria-modal="true" aria-labelledby="news-editor-title">
      <header><h2 id="news-editor-title">${item.id ? 'edit source' : 'add an RSS or Atom source'}</h2><button type="button" data-news-action="close-editor">close</button></header>
      <div class="news-editor-grid">
        <label class="wide"><span>feed URL</span><input id="news-source-url" type="url" value="${esc(item.url || '')}" autocomplete="off" placeholder="https://publisher.example/feed.xml"></label>
        <label><span>name</span><input id="news-source-name" type="text" value="${esc(item.name || '')}" maxlength="200" autocomplete="off"></label>
        <div><span>category</span><div class="news-choice-group" role="radiogroup" aria-label="source category">${[
          ['technology', 'technology'], ['taiwan', 'Taiwan'], ['world', 'world'], ['general', 'general'],
        ].map(([value, label]) => radio(value, item.category || 'general', label, 'editor-category')).join('')}</div></div>
        <div><span>language</span><div class="news-choice-group" role="radiogroup" aria-label="source language">${[
          ['en', 'English'], ['fr', 'French'], ['es', 'Spanish'], ['zh-Hans', 'Simplified Chinese'],
          ['zh-Hant', 'Traditional Chinese'], ['ja', 'Japanese'], ['ko', 'Korean'], ['ar', 'Arabic'],
          ['other', 'other'],
        ].map(([value, label]) => radio(value, item.language || 'en', label, 'editor-language')).join('')}</div></div>
        <div><span>priority</span><div class="news-choice-group" role="radiogroup" aria-label="source priority">${[
          ['0', 'low'], ['1', 'normal'], ['2', 'high'],
        ].map(([value, label]) => radio(value, String(item.priority ?? 1), label, 'editor-priority')).join('')}</div></div>
        <div><span>polling</span><div class="news-choice-group" role="radiogroup" aria-label="source polling schedule">${[
          ['inherit', 'with brief'], ['six_hours', 'every 6 hours'], ['daily', 'daily'],
        ].map(([value, label]) => radio(value, item.schedule || 'inherit', label, 'editor-schedule')).join('')}</div></div>
      </div>
      <p class="news-source-test" id="news-source-test" role="status" aria-live="polite">${item.id ? 'Existing URL is accepted. Test again if you change it.' : 'Test the source before saving. Nothing is stored by the test.'}</p>
      <footer>${item.id ? `<button type="button" class="news-delete" data-news-action="delete-source">delete source</button>` : '<span></span>'}<button type="button" data-news-action="test-source">test source</button><button type="button" class="news-primary" data-news-action="save-source"${editor.testedUrl ? '' : ' disabled'}>save source</button></footer>
    </section>
  </div>`;
}

function render() {
  const host = root();
  if (!host || !state) return;
  const config = state.configuration;
  const sources = state.sources || [];
  const jarvis = config.jarvis || {};
  host.innerHTML = `<div class="news-real-layout">
    <section class="news-real-main" aria-labelledby="news-real-title">
      <header class="news-real-head"><div><h2 id="news-real-title">news brief</h2><p>reviewed feeds, summarized by Aide, delivered to Home</p></div><div><span data-enabled="${config.enabled}">${config.enabled ? 'news is on' : 'news is off'}</span><button class="news-primary" type="button" data-news-action="toggle-news">${config.enabled ? 'turn off' : 'enable news'}</button></div></header>
      <p class="news-live-status" role="status" aria-live="polite">${config.last_safe_error ? esc(config.last_safe_error) : config.next_run_at ? `next brief ${esc(formatWhen(config.next_run_at))}` : 'nothing fetched until enabled'}</p>
      <section class="news-real-section" aria-labelledby="news-sources-title"><header><h3 id="news-sources-title">sources</h3><p>${sources.length} saved · each failure retries independently</p><button type="button" data-news-action="add-source">add source</button></header><ul class="news-source-list">${sources.map(sourceRow).join('') || '<li class="news-preview-empty">no sources yet</li>'}</ul></section>
      <section class="news-real-section" aria-labelledby="news-delivery-title"><header><h3 id="news-delivery-title">cadence and delivery</h3><p>automatic timezone · ${esc(localZone())}</p><button type="button" data-news-action="run-now"${config.enabled ? '' : ' disabled'}>run brief now</button></header>
        <div class="news-settings-grid"><div><h4>digest schedule</h4><div class="news-choice-group" role="radiogroup" aria-label="digest schedule">${radio('morning', config.cadence, 'every morning · 08:00', 'cadence')}${radio('evening', config.cadence, 'every evening · 18:00', 'cadence')}${radio('custom', config.cadence, 'custom time', 'cadence')}</div>${config.cadence === 'custom' ? `<label class="news-custom-time"><span>time in ${esc(localZone())}</span><input id="news-custom-time" type="text" inputmode="numeric" value="${esc(config.time_of_day)}" placeholder="07:30" aria-label="custom digest time"></label>` : ''}</div>
        <div><h4>delivery</h4><div class="news-delivery-row"><div><strong>home brief</strong><span>default destination</span></div>${switchButton({ checked: config.deliver_home, label: 'deliver News to Home', action: 'toggle-home' })}</div><div class="news-delivery-row"><div><strong>Jarvis direct message</strong><span>${esc(jarvis.available ? 'paired and ready' : jarvis.reason || 'pair Discord before enabling')}</span></div>${switchButton({ checked: config.deliver_jarvis, label: jarvis.available ? 'deliver News to Jarvis' : 'Jarvis delivery unavailable', action: 'toggle-jarvis', disabled: !jarvis.available })}</div></div></div>
      </section>
    </section>
    <aside class="news-real-preview" aria-label="latest News brief">${briefMarkup(state.latest_brief)}</aside>
  </div>${editorMarkup()}`;
}

async function loadNews(fetcher = fetch) {
  state = await requestJson('/api/news', {}, fetcher);
  render();
}

async function patchConfig(values) {
  state.configuration = await requestJson('/api/news/configuration', jsonOptions('PATCH', values));
  render();
}

function openEditor(source = null) {
  restoreFocus = document.activeElement;
  editor = { source: source ? { ...source } : { category: 'technology', language: 'en', priority: 1, schedule: 'inherit' }, testedUrl: source?.url || '', deleteArmed: false };
  render();
  document.getElementById('news-source-url')?.focus();
}

function closeEditor() {
  editor = null;
  render();
  if (restoreFocus?.isConnected) restoreFocus.focus();
  restoreFocus = null;
}

function selectedValue(group) {
  return root()?.querySelector(`[data-news-radio="${group}"][aria-checked="true"]`)?.dataset.value || '';
}

function sourceBody() {
  return {
    url: document.getElementById('news-source-url')?.value.trim() || '',
    name: document.getElementById('news-source-name')?.value.trim() || '',
    category: selectedValue('editor-category'),
    language: selectedValue('editor-language'),
    priority: Number(selectedValue('editor-priority')),
    schedule: selectedValue('editor-schedule'),
    enabled: editor?.source?.enabled ?? true,
  };
}

function chooseRadio(button) {
  const group = button.dataset.newsRadio;
  root()?.querySelectorAll(`[data-news-radio="${group}"]`).forEach(item => {
    const selected = item === button;
    item.setAttribute('aria-checked', String(selected));
    item.tabIndex = selected ? 0 : -1;
  });
}

async function handleRadio(button) {
  const group = button.dataset.newsRadio;
  const previous = group === 'cadence' ? state.configuration.cadence : '';
  chooseRadio(button);
  if (group === 'cadence') {
    try {
      await patchConfig({ cadence: button.dataset.value, timezone: localZone() });
    } catch (error) {
      const prior = root()?.querySelector(`[data-news-radio="cadence"][data-value="${CSS.escape(previous)}"]`);
      if (prior) chooseRadio(prior);
      throw error;
    }
  }
}

async function handleAction(button) {
  const action = button.dataset.newsAction || '';
  const actionEditor = editor;
  if (action === 'add-source') { openEditor(); return; }
  if (action === 'close-editor') { closeEditor(); return; }
  button.disabled = true;
  try {
    if (action === 'toggle-news') {
      await patchConfig({ enabled: !state.configuration.enabled, timezone: localZone() });
    } else if (action === 'toggle-home') {
      await patchConfig({ deliver_home: !state.configuration.deliver_home });
    } else if (action === 'toggle-jarvis') {
      await patchConfig({ deliver_jarvis: !state.configuration.deliver_jarvis });
    } else if (action.startsWith('toggle-source:')) {
      const id = action.split(':')[1];
      const source = state.sources.find(item => item.id === id);
      await requestJson(`/api/news/sources/${encodeURIComponent(id)}`, jsonOptions('PATCH', { enabled: !source.enabled }));
      await loadNews();
    } else if (action === 'run-now') {
      button.textContent = 'running…';
      await requestJson('/api/news/run', { method: 'POST' });
      await loadNews();
    } else if (action === 'test-source') {
      const value = document.getElementById('news-source-url')?.value.trim() || '';
      const requestId = (actionEditor?.testRequest || 0) + 1;
      if (!actionEditor) { button.disabled = false; return; }
      actionEditor.testRequest = requestId;
      const status = document.getElementById('news-source-test');
      status.textContent = 'checking the source safely…';
      const tested = await requestJson('/api/news/sources/test', jsonOptions('POST', { url: value }));
      const currentUrl = document.getElementById('news-source-url')?.value.trim() || '';
      if (editor !== actionEditor || actionEditor.testRequest !== requestId || currentUrl !== value) {
        button.disabled = false;
        return;
      }
      editor.testedUrl = tested.url;
      document.getElementById('news-source-url').value = tested.url;
      const name = document.getElementById('news-source-name');
      if (name && !name.value.trim()) name.value = tested.title || '';
      status.textContent = `${tested.items.length} recent item${tested.items.length === 1 ? '' : 's'} found. Nothing was saved.`;
      root()?.querySelector('[data-news-action="save-source"]')?.removeAttribute('disabled');
      button.disabled = false;
    } else if (action === 'save-source') {
      const body = sourceBody();
      if (body.url !== editor.testedUrl) throw new Error('test this URL before saving');
      const id = editor.source?.id;
      await requestJson(id ? `/api/news/sources/${encodeURIComponent(id)}` : '/api/news/sources', jsonOptions(id ? 'PATCH' : 'POST', body));
      editor = null;
      await loadNews();
    } else if (action === 'delete-source') {
      if (!editor.deleteArmed) {
        editor.deleteArmed = true;
        button.disabled = false;
        button.textContent = 'confirm delete';
        return;
      }
      await requestJson(`/api/news/sources/${encodeURIComponent(editor.source.id)}`, { method: 'DELETE' });
      editor = null;
      await loadNews();
    }
  } catch (error) {
    button.disabled = false;
    const status = document.getElementById('news-source-test');
    if (status && editor === actionEditor) status.textContent = safeMessage(error.message);
    else toast(safeMessage(error.message), 'error');
  }
}

async function saveCluster(button) {
  const cluster = state.latest_brief?.clusters?.[Number(button.dataset.newsSave)];
  const link = cluster?.links?.find(item => safeNewsUrl(item.url));
  const url = safeNewsUrl(link?.url);
  if (!link || !url) return;
  button.disabled = true;
  try {
    await requestJson('/api/read/save-news', jsonOptions('POST', {
      url, title: cluster.title, excerpt: cluster.summary, publisher: link.source,
    }));
    savedUrls.add(url);
    button.textContent = 'saved to Library';
    button.setAttribute('aria-pressed', 'true');
  } catch (error) {
    button.disabled = false;
    toast(safeMessage(error.message), 'error');
  }
}

function moveChoice(event, button) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const group = button.dataset.newsRadio;
  const items = [...root().querySelectorAll(`[data-news-radio="${group}"]`)];
  const current = items.indexOf(button);
  const target = event.key === 'Home' ? items[0] : event.key === 'End' ? items.at(-1)
    : items[(current + (['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1) + items.length) % items.length];
  target?.focus();
  handleRadio(target).catch(error => toast(safeMessage(error.message), 'error'));
}

function trapEditor(event) {
  if (!editor) return;
  if (event.key === 'Escape') { event.preventDefault(); closeEditor(); return; }
  if (event.key !== 'Tab') return;
  const dialog = root()?.querySelector('[role="dialog"]');
  const focusable = [...dialog?.querySelectorAll('button:not(:disabled), input:not(:disabled)') || []];
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}

function wireOnce() {
  const host = root();
  host.addEventListener('click', event => {
    const edit = event.target.closest('[data-news-edit]');
    if (edit) { openEditor(state.sources.find(item => item.id === edit.dataset.newsEdit)); return; }
    const radioButton = event.target.closest('[data-news-radio]');
    if (radioButton) { handleRadio(radioButton).catch(error => toast(safeMessage(error.message), 'error')); return; }
    const save = event.target.closest('[data-news-save]');
    if (save) { saveCluster(save); return; }
    const action = event.target.closest('[data-news-action]');
    if (action) handleAction(action);
  });
  host.addEventListener('input', event => {
    if (event.target.id !== 'news-source-url' || !editor) return;
    const changed = event.target.value.trim() !== editor.testedUrl;
    const save = root()?.querySelector('[data-news-action="save-source"]');
    if (save) save.disabled = changed;
    document.getElementById('news-source-test').textContent = changed
      ? 'URL changed. Test this source before saving.'
      : 'Source tested. You can save it now.';
  });
  host.addEventListener('keydown', event => {
    const choice = event.target.closest('[data-news-radio]');
    if (choice) moveChoice(event, choice);
    if (event.target.id === 'news-custom-time' && event.key === 'Enter') {
      event.preventDefault();
      event.target.blur();
    }
    trapEditor(event);
  });
  host.addEventListener('focusout', event => {
    if (event.target.id !== 'news-custom-time') return;
    const value = event.target.value.trim();
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) {
      toast('Use a 24-hour time like 07:30', 'error');
      return;
    }
    patchConfig({ time_of_day: value, timezone: localZone() }).catch(error => toast(safeMessage(error.message), 'error'));
  });
}

export async function initAideNews(fetcher = fetch) {
  if (!initialized) { initialized = true; wireOnce(); }
  await loadNews(fetcher);
}

export { localZone, formatWhen };

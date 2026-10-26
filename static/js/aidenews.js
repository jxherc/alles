import { toast } from './util.js';
import { formatDateTime, resolvedTimeZone, t, tp } from './i18n.js';

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
  return String(value || t('aide.news_unavailable')).replace(/jarvis/gi, 'Aide');
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
  if (!value) return t('aide.news_not_checked');
  const parsed = new Date(normalizeNewsTimestamp(value));
  if (Number.isNaN(parsed.getTime())) return t('aide.news_not_checked');
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
  const healthLabel = source.health === 'retry' ? t('aide.news_retry_scheduled') : source.health;
  const healthCopy = source.last_safe_error || (source.last_success_at
    ? t('aide.news_checked', { when: formatWhen(source.last_success_at) }) : t('aide.news_nothing_fetched'));
  const priority = source.priority >= 2 ? t('aide.news_priority_high') : source.priority === 0 ? t('aide.news_priority_low') : t('aide.news_priority_normal');
  return `<li class="news-source-row">
    <div class="news-source-name"><strong>${esc(source.name)}</strong><span>${esc(source.category)} · ${esc(source.language)} · ${priority}</span></div>
    <div class="news-source-health" data-health="${esc(source.health)}"><strong>${esc(healthLabel)}</strong><span>${esc(healthCopy)}</span></div>
    <div class="news-source-actions"><button type="button" data-news-edit="${esc(source.id)}">${esc(t('common.edit'))}</button>${switchButton({ checked: source.enabled, label: source.enabled ? t('aide.news_disable_source', { name: source.name }) : t('aide.news_enable_source', { name: source.name }), action: `toggle-source:${source.id}` })}</div>
  </li>`;
}

function briefMarkup(brief) {
  if (!brief) return `<div class="news-preview-empty"><strong>${esc(t('aide.news_no_brief'))}</strong><p>${esc(t('aide.news_no_brief_body'))}</p></div>`;
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
      ${firstUrl ? `<button type="button" data-news-save="${index}" aria-pressed="${saved}"${saved ? ' disabled' : ''}>${esc(saved ? t('aide.news_saved_library') : t('aide.news_save_library'))}</button>` : ''}
    </article>`;
  }).join('');
  const failures = brief.source_failures || [];
  return `<header class="news-preview-head"><h2>${esc(t('aide.news_latest_brief'))}</h2><span>${esc(tp('aide.news_clusters', clusters.length))} · ${esc(tp('aide.news_sources_count', sourceCount))}</span></header>
    <p class="news-preview-note">${esc(brief.status === 'summary_pending' ? t('aide.news_summary_pending') : t('aide.news_every_topic'))}</p>
    ${cards || `<div class="news-preview-empty"><strong>${esc(t('aide.news_no_stories'))}</strong></div>`}
    ${failures.length ? `<div class="news-digest-warning"><strong>${esc(t('aide.news_digest_available'))}</strong> ${esc(tp('aide.news_failures_retry', failures.length))}</div>` : ''}`;
}

function editorMarkup() {
  if (!editor) return '';
  const item = editor.source || {};
  return `<div class="news-editor-backdrop" data-news-editor-backdrop>
    <section class="news-editor" role="dialog" aria-modal="true" aria-labelledby="news-editor-title">
      <header><h2 id="news-editor-title">${esc(item.id ? t('aide.news_edit_source') : t('aide.news_add_feed'))}</h2><button type="button" data-news-action="close-editor">${esc(t('common.close'))}</button></header>
      <div class="news-editor-grid">
        <label class="wide"><span>${esc(t('aide.news_feed_url'))}</span><input id="news-source-url" type="url" value="${esc(item.url || '')}" autocomplete="off" placeholder="https://publisher.example/feed.xml"></label>
        <label><span>${esc(t('aide.news_name'))}</span><input id="news-source-name" type="text" value="${esc(item.name || '')}" maxlength="200" autocomplete="off"></label>
        <div><span>${esc(t('aide.news_category'))}</span><div class="news-choice-group" role="radiogroup" aria-label="${esc(t('aide.news_source_category'))}">${[
          ['technology', t('aide.news_cat_technology')], ['taiwan', t('aide.news_cat_taiwan')], ['world', t('aide.news_cat_world')], ['general', t('aide.news_cat_general')],
        ].map(([value, label]) => radio(value, item.category || 'general', label, 'editor-category')).join('')}</div></div>
        <div><span>${esc(t('aide.news_language'))}</span><div class="news-choice-group" role="radiogroup" aria-label="${esc(t('aide.news_source_language'))}">${[
          ['en', t('aide.news_lang_en')], ['fr', t('aide.news_lang_fr')], ['es', t('aide.news_lang_es')], ['zh-Hans', t('aide.news_lang_zh_hans')],
          ['zh-Hant', t('aide.news_lang_zh_hant')], ['ja', t('aide.news_lang_ja')], ['ko', t('aide.news_lang_ko')], ['ar', t('aide.news_lang_ar')],
          ['other', t('aide.news_lang_other')],
        ].map(([value, label]) => radio(value, item.language || 'en', label, 'editor-language')).join('')}</div></div>
        <div><span>${esc(t('aide.news_priority'))}</span><div class="news-choice-group" role="radiogroup" aria-label="${esc(t('aide.news_source_priority'))}">${[
          ['0', t('aide.news_pri_low')], ['1', t('aide.news_pri_normal')], ['2', t('aide.news_pri_high')],
        ].map(([value, label]) => radio(value, String(item.priority ?? 1), label, 'editor-priority')).join('')}</div></div>
        <div><span>${esc(t('aide.news_polling'))}</span><div class="news-choice-group" role="radiogroup" aria-label="${esc(t('aide.news_source_polling'))}">${[
          ['inherit', t('aide.news_poll_inherit')], ['six_hours', t('aide.sched_every_six_hours')], ['daily', t('aide.news_poll_daily')],
        ].map(([value, label]) => radio(value, item.schedule || 'inherit', label, 'editor-schedule')).join('')}</div></div>
      </div>
      <p class="news-source-test" id="news-source-test" role="status" aria-live="polite">${esc(item.id ? t('aide.news_url_accepted') : t('aide.news_test_first'))}</p>
      <footer>${item.id ? `<button type="button" class="news-delete" data-news-action="delete-source">${esc(t('aide.news_delete_source'))}</button>` : '<span></span>'}<button type="button" data-news-action="test-source">${esc(t('aide.news_test_source'))}</button><button type="button" class="news-primary" data-news-action="save-source"${editor.testedUrl ? '' : ' disabled'}>${esc(t('aide.news_save_source'))}</button></footer>
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
      <header class="news-real-head"><div><h2 id="news-real-title">${esc(t('aide.news_brief'))}</h2><p>${esc(t('aide.news_brief_sub'))}</p></div><div><span data-enabled="${config.enabled}">${esc(config.enabled ? t('aide.news_is_on') : t('aide.news_is_off'))}</span><button class="news-primary" type="button" data-news-action="toggle-news">${esc(config.enabled ? t('aide.news_turn_off') : t('aide.news_enable'))}</button></div></header>
      <p class="news-live-status" role="status" aria-live="polite">${config.last_safe_error ? esc(config.last_safe_error) : config.next_run_at ? esc(t('aide.news_next_brief', { when: formatWhen(config.next_run_at) })) : esc(t('aide.news_nothing_until_enabled'))}</p>
      <section class="news-real-section" aria-labelledby="news-sources-title"><header><h3 id="news-sources-title">${esc(t('aide.step_sources'))}</h3><p>${esc(t('aide.news_sources_saved', { count: sources.length }))}</p><button type="button" data-news-action="add-source">${esc(t('aide.news_add_source'))}</button></header><ul class="news-source-list">${sources.map(sourceRow).join('') || `<li class="news-preview-empty">${esc(t('aide.news_no_sources'))}</li>`}</ul></section>
      <section class="news-real-section" aria-labelledby="news-delivery-title"><header><h3 id="news-delivery-title">${esc(t('aide.news_cadence_delivery'))}</h3><p>${esc(t('aide.news_auto_timezone', { zone: localZone() }))}</p><button type="button" data-news-action="run-now"${config.enabled ? '' : ' disabled'}>${esc(t('aide.news_run_now'))}</button></header>
        <div class="news-settings-grid"><div><h4>${esc(t('aide.news_digest_schedule'))}</h4><div class="news-choice-group" role="radiogroup" aria-label="${esc(t('aide.news_digest_schedule'))}">${radio('morning', config.cadence, t('aide.news_every_morning'), 'cadence')}${radio('evening', config.cadence, t('aide.news_every_evening'), 'cadence')}${radio('custom', config.cadence, t('aide.news_custom_time'), 'cadence')}</div>${config.cadence === 'custom' ? `<label class="news-custom-time"><span>${esc(t('aide.news_time_in', { zone: localZone() }))}</span><input id="news-custom-time" type="text" inputmode="numeric" value="${esc(config.time_of_day)}" placeholder="07:30" aria-label="${esc(t('aide.news_custom_digest_time'))}"></label>` : ''}</div>
        <div><h4>${esc(t('aide.news_delivery'))}</h4><div class="news-delivery-row"><div><strong>${esc(t('aide.news_home_brief'))}</strong><span>${esc(t('aide.news_default_destination'))}</span></div>${switchButton({ checked: config.deliver_home, label: t('aide.news_deliver_home'), action: 'toggle-home' })}</div><div class="news-delivery-row"><div><strong>${esc(t('aide.news_discord_dm'))}</strong><span>${esc(jarvis.available ? t('aide.news_paired_ready') : jarvis.reason || t('aide.news_pair_discord'))}</span></div>${switchButton({ checked: config.deliver_jarvis, label: jarvis.available ? t('aide.news_deliver_discord') : t('aide.news_discord_unavailable'), action: 'toggle-jarvis', disabled: !jarvis.available })}</div></div></div>
      </section>
    </section>
    <aside class="news-real-preview" aria-label="${esc(t('aide.news_latest_aria'))}">${briefMarkup(state.latest_brief)}</aside>
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
      button.textContent = t('aide.news_running');
      await requestJson('/api/news/run', { method: 'POST' });
      await loadNews();
    } else if (action === 'test-source') {
      const value = document.getElementById('news-source-url')?.value.trim() || '';
      const requestId = (actionEditor?.testRequest || 0) + 1;
      if (!actionEditor) { button.disabled = false; return; }
      actionEditor.testRequest = requestId;
      const status = document.getElementById('news-source-test');
      status.textContent = t('aide.news_checking_source');
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
      status.textContent = tp('aide.news_items_found', tested.items.length);
      root()?.querySelector('[data-news-action="save-source"]')?.removeAttribute('disabled');
      button.disabled = false;
    } else if (action === 'save-source') {
      const body = sourceBody();
      if (body.url !== editor.testedUrl) throw new Error(t('aide.news_test_before_save'));
      const id = editor.source?.id;
      await requestJson(id ? `/api/news/sources/${encodeURIComponent(id)}` : '/api/news/sources', jsonOptions(id ? 'PATCH' : 'POST', body));
      editor = null;
      await loadNews();
    } else if (action === 'delete-source') {
      if (!editor.deleteArmed) {
        editor.deleteArmed = true;
        button.disabled = false;
        button.textContent = t('aide.news_confirm_delete');
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
    button.textContent = t('aide.news_saved_library');
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
      ? t('aide.news_url_changed')
      : t('aide.news_source_tested');
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
      toast(t('aide.news_err_time'), 'error');
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

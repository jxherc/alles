import { confirm as confirmDialog } from './dialog.js';
import { urlForApp } from './subdomain.js';

let _bound = false;
let _overviewAbort = null;
let _modelChoices = new Map();
let _projectId = '';
let _state = freshState();

const PROJECT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function freshState() {
  return { query: '', request: {}, results: [], overviewSeed: [], overview: {}, evidence: [], model: {} };
}

function el(id) { return document.getElementById(id); }
function text(id, value) { const node = el(id); if (node) node.textContent = value || ''; }

async function jsonRequest(url, options = {}) {
  const response = await fetch(url, options);
  let body = {};
  try { body = await response.json(); } catch {}
  if (!response.ok) {
    const error = new Error(body.detail || 'request failed');
    error.code = body.code || `http_${response.status}`;
    error.failure_type = body.failure_type || '';
    error.attempted_sources = body.attempted_sources || [];
    error.status = response.status;
    throw error;
  }
  return body;
}

function pressed(id) { return el(id)?.getAttribute('aria-pressed') === 'true'; }
function setPressed(id, value) {
  const node = el(id);
  if (!node) return;
  node.setAttribute('aria-pressed', String(!!value));
  node.classList.toggle('active', !!value);
}

function status(message) { text('andromeda-status', message); }

export function validatedProjectId(value = '') {
  const id = String(value || '').trim();
  return PROJECT_ID.test(id) ? id.toLowerCase() : '';
}

export function withProjectContext(url, projectId = '') {
  const valid = validatedProjectId(projectId);
  if (!valid) return url;
  const target = new URL(url);
  target.searchParams.set('project_id', valid);
  return target.toString();
}

export function failureSummary(payload = {}) {
  const type = String(payload.failure_type || payload.code || '').replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, 80);
  const attempted = Array.isArray(payload.attempted_sources)
    ? payload.attempted_sources
      .map(value => String(value || '').replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, 80))
      .filter(Boolean)
      .slice(0, 8)
    : [];
  return [type ? `failure: ${type.replaceAll('_', ' ')}` : '', attempted.length ? `tried: ${attempted.join(', ')}` : '']
    .filter(Boolean).join(' · ');
}

function failureMessage(message, payload = {}) {
  const details = failureSummary(payload);
  return [message, details].filter(Boolean).join(' · ');
}

function showOverview(show = true) {
  const node = el('andromeda-overview');
  if (node) node.hidden = !show;
}

function clearOverview(message = '') {
  _state.overview = {};
  _state.evidence = [];
  el('andromeda-claims')?.replaceChildren();
  el('andromeda-evidence')?.replaceChildren();
  const details = el('andromeda-evidence-details');
  if (details) details.hidden = true;
  text('andromeda-overview-state', message);
  showRecovery(false);
}

function showRecovery(show, kind = '') {
  const node = el('andromeda-recovery');
  if (!node) return;
  node.hidden = !show;
  node.dataset.kind = kind;
}

function resultNode(result) {
  const row = document.createElement('article');
  row.className = 'andromeda-result';
  const check = document.createElement('input');
  check.type = 'checkbox';
  check.className = 'andromeda-result-select';
  check.dataset.url = result.url;
  check.setAttribute('aria-label', `select ${result.title}`);
  const body = document.createElement('div');
  const site = document.createElement('div');
  site.className = 'andromeda-result-site';
  site.textContent = `${result.publisher || ''} · ${result.source_kind || 'web'}`;
  const quality = document.createElement('span');
  quality.className = 'andromeda-source-chip';
  quality.textContent = `q${result.source_quality || 5}`;
  site.appendChild(quality);
  const link = document.createElement('a');
  link.href = result.url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.textContent = result.title || result.url;
  const snippet = document.createElement('p');
  snippet.textContent = result.snippet || 'no snippet was returned';
  body.append(site, link, snippet);
  row.append(check, body);
  return row;
}

export function renderAndromedaResults(results, state = 'ready') {
  const list = el('andromeda-results');
  if (!list) return;
  list.replaceChildren();
  for (const result of results || []) list.appendChild(resultNode(result));
  if (!results?.length) {
    const empty = document.createElement('div');
    empty.className = 'andromeda-empty';
    empty.textContent = {
      disabled: 'normal results are off for this search.',
      loading: 'finding normal results…',
      empty: 'no normal results found. try a broader query.',
      error: 'normal search failed. you can retry or change providers in Settings.',
      offline: 'you appear to be offline. saved searches are still available.',
    }[state] || 'search to see normal results.';
    list.appendChild(empty);
  }
  const actions = el('andromeda-actions');
  if (actions) actions.hidden = !_state.query;
}

function renderEvidence(sources) {
  _state.evidence = sources || [];
  const list = el('andromeda-evidence');
  if (!list) return;
  list.replaceChildren();
  for (const source of _state.evidence) {
    const node = document.createElement('div');
    node.className = 'andromeda-evidence-source';
    const title = document.createElement('strong');
    title.textContent = `${source.id} · ${source.title}`;
    const meta = document.createElement('small');
    meta.textContent = `${source.source_kind} · quality ${source.source_quality}`;
    node.append(title, meta);
    for (const passage of source.passages || []) {
      const quote = document.createElement('blockquote');
      quote.textContent = passage;
      node.appendChild(quote);
    }
    list.appendChild(node);
  }
  const details = el('andromeda-evidence-details');
  if (details) details.hidden = !_state.evidence.length;
}

function renderClaim(claim, index) {
  const list = el('andromeda-claims');
  if (!list) return;
  const node = document.createElement('p');
  node.className = 'andromeda-claim';
  node.appendChild(document.createTextNode(claim.text || ''));
  const refs = document.createElement('span');
  refs.className = 'andromeda-citations';
  (claim.citations || []).forEach((citation, citationIndex) => {
    const link = document.createElement('a');
    link.className = 'andromeda-citation';
    link.href = citation.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = String(citationIndex + 1);
    link.title = `${citation.title}: ${citation.quote}`;
    refs.appendChild(link);
  });
  node.appendChild(refs);
  node.dataset.claim = String(index);
  list.appendChild(node);
}

function renderCompleteOverview(overview) {
  _state.overview = overview || {};
  const list = el('andromeda-claims');
  list?.replaceChildren();
  (_state.overview.claims || []).forEach(renderClaim);
  const freshness = _state.overview.freshness || {};
  const checked = freshness.checked_on ? ` · checked ${freshness.checked_on}` : '';
  if (_state.overview.status === 'ready') {
    text('andromeda-overview-state', `supported by exact source passages${checked}`);
    showRecovery(false);
  } else {
    text('andromeda-overview-state', `not enough trustworthy evidence for an overview${checked}`);
    showRecovery(true, 'insufficient_evidence');
  }
}

export function parseSseFrames(buffer) {
  const frames = [];
  let rest = buffer;
  while (rest.includes('\n\n')) {
    const split = rest.indexOf('\n\n');
    const frame = rest.slice(0, split);
    rest = rest.slice(split + 2);
    const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
    if (data) frames.push(data);
  }
  return { frames, rest };
}

function selectedExactModel() {
  return _modelChoices.get(el('andromeda-exact-model')?.value || '') || {};
}

async function previewOverview() {
  const params = new URLSearchParams({ band: el('andromeda-band')?.value || 'standard' });
  const exact = selectedExactModel();
  if (exact.endpoint_id) {
    params.set('endpoint_id', exact.endpoint_id);
    params.set('model', exact.model);
  }
  return jsonRequest(`/api/andromeda/overview/preview?${params}`);
}

async function startOverview(query, results) {
  showOverview(true);
  clearOverview('checking model and source evidence…');
  const stop = el('andromeda-cancel-overview');
  if (stop) stop.hidden = false;
  let preview;
  try {
    preview = await previewOverview();
  } catch (error) {
    text('andromeda-overview-state', failureMessage(`${error.message}. normal links are still available.`, error));
    showRecovery(true, error.code);
    if (stop) stop.hidden = true;
    return;
  }
  _state.model = preview;
  text('andromeda-model', `${preview.model} · ${preview.endpoint} · ${preview.privacy_class}`);
  const confirmation = {};
  if (preview.privacy_class === 'remote') {
    const allowed = await confirmDialog(`send this query and selected web evidence to ${preview.endpoint} / ${preview.model}?`);
    if (!allowed) {
      text('andromeda-overview-state', 'overview cancelled before anything was sent. normal links are unchanged.');
      showRecovery(true, 'remote_not_confirmed');
      if (stop) stop.hidden = true;
      return;
    }
    confirmation.confirmed_endpoint_id = preview.endpoint_id;
    confirmation.confirmed_model = preview.model;
  }
  _overviewAbort?.abort();
  _overviewAbort = new AbortController();
  const exact = selectedExactModel();
  let response;
  try {
    response = await fetch('/api/andromeda/overview', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      signal: _overviewAbort.signal,
      body: JSON.stringify({
        query,
        results,
        band: el('andromeda-band')?.value || 'standard',
        endpoint_id: exact.endpoint_id || '',
        model: exact.model || '',
        ...confirmation,
      }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw Object.assign(new Error(body.detail || 'overview failed'), {
        code: body.code,
        failure_type: body.failure_type,
        attempted_sources: body.attempted_sources,
      });
    }
    text('andromeda-overview-state', 'reading selected sources…');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let claimIndex = 0;
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done }).replace(/\r\n/g, '\n');
      const parsed = parseSseFrames(buffer);
      buffer = parsed.rest;
      for (const frame of parsed.frames) {
        if (frame === '[DONE]') continue;
        let event;
        try { event = JSON.parse(frame); } catch { continue; }
        if (event.type === 'evidence') renderEvidence(event.sources);
        if (event.type === 'claim') renderClaim(event.claim, claimIndex++);
        if (event.type === 'overview') renderCompleteOverview(event.overview);
        if (event.type === 'error') {
          text('andromeda-overview-state', failureMessage(
            event.detail || 'overview failed; normal links are still available', event,
          ));
          showRecovery(true, event.code);
        }
      }
      if (done) break;
    }
  } catch (error) {
    if (error.name === 'AbortError') text('andromeda-overview-state', 'overview stopped. normal links are unchanged.');
    else text('andromeda-overview-state', failureMessage(
      `${error.message || 'overview failed'}. normal links are still available.`, error,
    ));
    showRecovery(true, error.name === 'AbortError' ? 'cancelled' : error.code || 'overview_failed');
  } finally {
    if (stop) stop.hidden = true;
  }
}

export async function runAndromedaSearch(queryValue = '') {
  const input = el('andromeda-query');
  const query = String(queryValue || input?.value || '').trim();
  if (!query) { input?.focus(); return; }
  if (input) input.value = query;
  _overviewAbort?.abort();
  _state = freshState();
  _state.query = query;
  renderAndromedaResults([], 'loading');
  clearOverview();
  showOverview(pressed('andromeda-overview-toggle') && !/(^|\s)!ai(?=\s|$)/i.test(query));
  status('searching…');
  const request = {
    query,
    normal_results: pressed('andromeda-results-toggle'),
    overview: pressed('andromeda-overview-toggle'),
  };
  _state.request = { ...request, band: el('andromeda-band')?.value || 'standard' };
  try {
    const result = await jsonRequest('/api/andromeda/search', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(request),
    });
    _state.query = result.query;
    _state.results = result.results || [];
    _state.overviewSeed = result.overview_seed || _state.results;
    if (input) input.value = result.query + (result.used_no_ai ? ' !ai' : '');
    renderAndromedaResults(_state.results, result.status);
    const searchFailure = failureSummary(result);
    text('andromeda-result-meta', result.normal_results_enabled
      ? [`${result.provider || 'provider'} · ${result.elapsed_ms} ms`, searchFailure].filter(Boolean).join(' · ')
      : 'hidden for this search');
    if (result.status === 'partial') {
      status(failureMessage('some results loaded; one provider had trouble', result));
    } else if (result.status === 'error') {
      status(failureMessage('normal search failed', result));
    } else {
      status(`${_state.results.length} normal result${_state.results.length === 1 ? '' : 's'} ready`);
    }
    if (result.overview_requested && _state.overviewSeed.length) {
      await startOverview(result.query, _state.overviewSeed);
    } else if (result.status === 'error') {
      showOverview(true);
      text('andromeda-overview-state', failureMessage(
        'normal search failed. no sources were available for an overview.', result,
      ));
      showRecovery(true, result.failure_type || 'search_failed');
    } else if (result.overview_requested) {
      showOverview(true);
      text('andromeda-overview-state', 'no safe source links were available for an overview.');
      showRecovery(true, 'no_sources');
    } else {
      showOverview(false);
    }
  } catch (error) {
    renderAndromedaResults([], navigator.onLine === false ? 'offline' : 'error');
    status(failureMessage(error.message || 'search failed', error));
    showOverview(true);
    text('andromeda-overview-state', failureMessage(
      'overview could not start because search did not return sources.', error,
    ));
    showRecovery(true, error.code || 'search_failed');
  }
}

function selectedLinks() {
  return [...document.querySelectorAll('.andromeda-result-select:checked')].map(node => node.dataset.url).filter(Boolean);
}

async function saveCurrent() {
  if (!_state.query) return;
  try {
    await jsonRequest('/api/andromeda/saved', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        query: _state.query, request: _state.request, results: _state.results,
        overview: _state.overview, evidence: _state.evidence, model: _state.model,
      }),
    });
    status('search saved');
    await loadSaved();
  } catch (error) { status(error.message); }
}

function reopen(saved) {
  _state = {
    query: saved.query, request: saved.request || {}, results: saved.results || [],
    overviewSeed: saved.results || [], overview: saved.overview || {},
    evidence: saved.evidence || [], model: saved.model || {},
  };
  if (el('andromeda-query')) el('andromeda-query').value = saved.query;
  setPressed('andromeda-results-toggle', saved.request?.normal_results !== false);
  setPressed('andromeda-overview-toggle', saved.request?.overview !== false);
  if (saved.request?.band && el('andromeda-band')) el('andromeda-band').value = saved.request.band;
  renderAndromedaResults(_state.results, _state.results.length ? 'ready' : 'empty');
  renderEvidence(_state.evidence);
  showOverview(!!Object.keys(_state.overview).length);
  if (_state.overview?.status) renderCompleteOverview(_state.overview);
  text('andromeda-model', [_state.model.model, _state.model.endpoint].filter(Boolean).join(' · '));
  text('andromeda-result-meta', `saved · checked ${saved.checked_at || ''}`);
  status('saved search reopened');
}

async function loadSaved() {
  const list = el('andromeda-saved-list');
  if (!list) return;
  list.replaceChildren();
  try {
    const { searches } = await jsonRequest('/api/andromeda/saved');
    if (!searches.length) { list.textContent = 'nothing saved yet'; return; }
    for (const item of searches) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'andromeda-saved-row';
      button.textContent = item.query;
      button.title = `checked ${item.checked_at}`;
      button.addEventListener('click', async () => {
        try { reopen(await jsonRequest(`/api/andromeda/saved/${item.id}`)); }
        catch (error) { status(error.message); }
      });
      list.appendChild(button);
    }
  } catch { list.textContent = 'saved searches unavailable'; }
}

async function loadModelChoices() {
  const select = el('andromeda-exact-model');
  if (!select) return;
  try {
    const endpoints = await jsonRequest('/api/models');
    let index = 0;
    for (const endpoint of endpoints) {
      for (const model of endpoint.models || []) {
        const key = String(++index);
        _modelChoices.set(key, { endpoint_id: endpoint.id, model });
        const option = document.createElement('option');
        option.value = key;
        option.textContent = `${model} · ${endpoint.name}`;
        select.appendChild(option);
      }
    }
  } catch {}
}

async function runDeepResearch() {
  if (!_state.query) return;
  try {
    const preview = await jsonRequest('/api/andromeda/deep-research/preview');
    const confirmation = {};
    if (preview.privacy_class === 'remote') {
      const allowed = await confirmDialog(`send this research request and Project context to ${preview.endpoint} / ${preview.model}?`);
      if (!allowed) return;
      confirmation.confirmed_endpoint_id = preview.endpoint_id;
      confirmation.confirmed_model = preview.model;
    }
    const run = await jsonRequest('/api/andromeda/deep-research', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        query: _state.query,
        session_id: '',
        project_id: _projectId,
        ...confirmation,
      }),
    });
    status('Jarvis research started. opening its Aide conversation…');
    location.href = `${urlForApp('aide')}#${run.session_id}`;
  } catch (error) { status(error.message); }
}

async function loadProjectContext() {
  // Only carry the opaque ID into the explicit deep-research action. Do not load
  // Project instructions, paths, or other private context into normal search.
  _projectId = validatedProjectId(new URLSearchParams(location.search).get('project_id'));
}

function explainSelected() {
  const links = selectedLinks();
  if (!links.length) { status('select one or more normal results first'); return; }
  const request = `Explain these selected links using only their contents. Cite each link and say when evidence is missing:\n${links.join('\n')}`;
  location.href = `${urlForApp('aide')}?ask=${encodeURIComponent(request)}`;
}

function bindRecovery() {
  el('andromeda-recovery')?.addEventListener('click', event => {
    const action = event.target.closest('[data-andromeda-recovery]')?.dataset.andromedaRecovery;
    if (action === 'retry') runAndromedaSearch();
    if (action === 'broaden') {
      const broad = (el('andromeda-query')?.value || '').replace(/"([^"]+)"/g, '$1').replace(/(^|\s)![^\s]+/g, ' ').replace(/\s+/g, ' ').trim();
      runAndromedaSearch(broad);
    }
    if (action === 'edit') el('andromeda-query')?.focus();
    if (action === 'results') el('andromeda-results-title')?.scrollIntoView({ block: 'start' });
  });
}

export async function initAndromeda() {
  if (!_bound) {
    _bound = true;
    el('andromeda-form')?.addEventListener('submit', event => { event.preventDefault(); runAndromedaSearch(); });
    for (const id of ['andromeda-results-toggle', 'andromeda-overview-toggle']) {
      el(id)?.addEventListener('click', () => setPressed(id, !pressed(id)));
    }
    el('andromeda-cancel-overview')?.addEventListener('click', () => _overviewAbort?.abort());
    el('andromeda-save')?.addEventListener('click', saveCurrent);
    el('andromeda-explain')?.addEventListener('click', explainSelected);
    el('andromeda-deep')?.addEventListener('click', runDeepResearch);
    bindRecovery();
    await loadModelChoices();
  }
  await loadProjectContext();
  try {
    const settings = await jsonRequest('/api/settings');
    setPressed('andromeda-results-toggle', settings.andromeda_normal_results !== false);
    setPressed('andromeda-overview-toggle', settings.andromeda_overview !== false);
    if (el('andromeda-band')) el('andromeda-band').value = settings.andromeda_model_band || 'standard';
  } catch {}
  await loadSaved();
  const query = new URLSearchParams(location.search).get('q');
  if (query && !_state.query) runAndromedaSearch(query);
}

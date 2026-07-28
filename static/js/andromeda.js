import { initCustomDropdowns, populateDropdown, setDropdownValue } from './dropdown.js?v=212';
import { urlForApp } from './subdomain.js?v=237';
import { confirm as confirmDialog } from './dialog.js';
import { formatDate, formatDateTime, t as tr, tp as trp } from './i18n.js';

let _bound = false;
let _overviewAbort = null;
let _searchAbort = null;
let _verificationJobId = '';
let _verificationPollTimer = 0;
let _searchGeneration = 0;
let _modelChoices = new Map();
let _settingsState = {};
let _searchConfigurationWrite = Promise.resolve();
let _searchConfigurationGeneration = 0;
let _state = freshState();

const PROJECT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CATEGORIES = new Set(['all', 'images', 'news', 'videos']);
const PAGE_SIZES = Object.freeze({ all: 10, images: 30, news: 20, videos: 20 });
const NORMAL_RESULT_COUNTS = new Set([3, 5, 8, 10, 20]);

function freshState() {
  return {
    rawQuery: '', query: '', category: 'all', request: {}, results: [], overviewSeed: [],
    overview: {}, evidence: [], model: {}, verification: {}, verifierModel: {},
    hasMore: false, usedNoAi: false,
    resultStatus: 'empty', documentScope: null,
  };
}

export function queryWithNoAi(query = '', usedNoAi = false) {
  const clean = String(query || '').replace(/(^|\s)!ai(?=\s|$)/ig, ' ').replace(/\s+/g, ' ').trim();
  return usedNoAi && clean ? `${clean} !ai` : clean;
}

export function continuationQuery(query = '', request = {}, usedNoAi = false) {
  const selected = String(query || '').trim() || String(request?.query || '').trim();
  return queryWithNoAi(selected, usedNoAi);
}

function el(id) { return document.getElementById(id); }
function text(id, value) { const node = el(id); if (node) node.textContent = value || ''; }

async function jsonRequest(url, options = {}) {
  const response = await fetch(url, options);
  let body = {};
  try { body = await response.json(); } catch {}
  if (!response.ok) {
    const error = new Error(body.detail || tr('common.request_failed'));
    error.code = body.code || `http_${response.status}`;
    error.failure_type = body.failure_type || '';
    error.attempted_sources = body.attempted_sources || [];
    error.status = response.status;
    throw error;
  }
  return body;
}

function pressed(id) {
  const node = el(id);
  return node?.getAttribute('aria-checked') === 'true' || node?.getAttribute('aria-pressed') === 'true';
}

function setPressed(id, value) {
  const node = el(id);
  if (!node) return;
  const on = !!value;
  node.setAttribute('aria-pressed', String(on));
  if (node.getAttribute('role') === 'switch') node.setAttribute('aria-checked', String(on));
  node.classList.toggle('active', on);
}

function status(message) { text('andromeda-status', message); }

function setPageState(state) {
  const page = el('andromeda-view');
  if (page) page.dataset.state = state;
}

function category() {
  const value = el('andromeda-view')?.dataset.category || 'all';
  return CATEGORIES.has(value) ? value : 'all';
}

function pageSize(currentCategory) {
  if (currentCategory !== 'all') return PAGE_SIZES[currentCategory];
  const configured = Number.parseInt(_settingsState.search_result_count, 10);
  return NORMAL_RESULT_COUNTS.has(configured) ? configured : 8;
}

function setCategory(next, { search = true } = {}) {
  const value = CATEGORIES.has(next) ? next : 'all';
  const page = el('andromeda-view');
  if (page) page.dataset.category = value;
  _state.category = value;
  document.querySelectorAll('[data-andromeda-category]').forEach(button => {
    const active = button.dataset.andromedaCategory === value;
    button.classList.toggle('active', active);
    button.setAttribute('aria-current', active ? 'page' : 'false');
  });
  document.querySelectorAll('[data-andromeda-view]').forEach(view => {
    view.hidden = view.dataset.andromedaView !== value;
  });
  if (value !== 'all') showOverview(false);
  if (search && _state.rawQuery) {
    runAndromedaSearch(_state.rawQuery, { category: value });
  }
}

export function validatedProjectId(value = '') {
  const id = String(value || '').trim();
  return PROJECT_ID.test(id) ? id.toLowerCase() : '';
}

export function withProjectContext(url, projectId = '') {
  const raw = String(url || '');
  const valid = validatedProjectId(projectId);
  const absolute = /^[a-z][a-z\d+.-]*:/i.test(raw);
  const protocolRelative = raw.startsWith('//');
  const target = new URL(raw, 'http://alles.invalid');
  if (valid) target.searchParams.set('project_id', valid);
  else target.searchParams.delete('project_id');
  if (absolute) return target.toString();
  const relative = `${target.pathname}${target.search}${target.hash}`;
  return protocolRelative ? `//${target.host}${relative}` : relative;
}

export function failureSummary(payload = {}) {
  const type = String(payload.failure_type || payload.code || '')
    .replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, 80);
  const attempted = Array.isArray(payload.attempted_sources)
    ? payload.attempted_sources
      .map(value => String(value || '').replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, 80))
      .filter(Boolean)
      .slice(0, 8)
    : [];
  return [
    type ? tr('andromeda.failure', { type: type.replaceAll('_', ' ') }) : '',
    attempted.length ? tr('andromeda.tried', { sources: attempted.join(', ') }) : '',
  ].filter(Boolean).join(' · ');
}

function failureMessage(message, payload = {}) {
  return [message, failureSummary(payload)].filter(Boolean).join(' · ');
}

function safeUrl(value) {
  try {
    const url = new URL(String(value || ''));
    return ['http:', 'https:'].includes(url.protocol) ? url : null;
  } catch { return null; }
}

export function mediaUrl(value) {
  const url = safeUrl(value);
  if (!url || /\.svg(?:$|[?#])/i.test(url.href)) return '';
  return `/api/andromeda/media?url=${encodeURIComponent(url.href)}`;
}

function sourceInitials(result) {
  const source = String(result.publisher || safeUrl(result.url)?.hostname || 'web').replace(/^www\./, '');
  return source.split(/[.\s-]+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toLowerCase() || 'w';
}

function mediaFrame(result, { favicon = false, video = false } = {}) {
  const frame = document.createElement('span');
  frame.className = favicon ? 'andromeda-source-mark' : 'andromeda-media-frame';
  const fallback = document.createElement('span');
  fallback.textContent = favicon ? sourceInitials(result) : tr('andromeda.image_unavailable');
  const raw = favicon
    ? result.favicon_url
    : (result.thumbnail_url || result.image_url || '');
  const width = Number(result.width);
  const height = Number(result.height);
  if (!favicon && width > 0 && height > 0) frame.style.aspectRatio = `${width} / ${height}`;
  const src = mediaUrl(raw);
  if (src) {
    const image = document.createElement('img');
    image.src = src;
    image.alt = favicon ? '' : (result.title || 'search result');
    image.loading = favicon ? 'eager' : 'lazy';
    image.decoding = 'async';
    image.addEventListener('load', () => {
      image.classList.add('loaded');
      fallback.remove();
    }, { once: true });
    image.addEventListener('error', () => image.remove(), { once: true });
    frame.appendChild(image);
  }
  frame.appendChild(fallback);
  if (video) {
    const play = document.createElement('span');
    play.className = 'andromeda-play-mark';
    play.textContent = '▶';
    frame.appendChild(play);
    if (result.duration) {
      const duration = document.createElement('span');
      duration.className = 'andromeda-duration';
      duration.textContent = result.duration;
      frame.appendChild(duration);
    }
  }
  return frame;
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
  const evidence = el('andromeda-evidence');
  const toggle = el('andromeda-evidence-toggle');
  if (evidence) evidence.hidden = true;
  if (toggle) {
    toggle.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
    toggle.textContent = tr('andromeda.show_sources');
  }
  const key = el('andromeda-key-answer');
  if (key) key.hidden = true;
  text('andromeda-key-answer-text', '');
  text('andromeda-overview-state', message);
  showRecovery(false);
}

function showRecovery(show, kind = '') {
  const node = el('andromeda-recovery');
  if (!node) return;
  node.hidden = !show;
  node.dataset.kind = kind;
}

function makeExternalLink(result, className) {
  const href = safeUrl(result.url);
  const link = document.createElement(href ? 'a' : 'span');
  link.className = className;
  link.textContent = result.title || result.url || tr('andromeda.untitled_result');
  if (href) {
    link.href = href.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
  }
  return link;
}

const RESULT_DATE_PATTERNS = [
  /\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4}\b/i,
  /\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{4}\b/i,
  /\b\d{4}-\d{2}-\d{2}\b/,
];

function bestResultDateFocus(snippet) {
  const answer = String(snippet || '');
  const candidates = RESULT_DATE_PATTERNS.flatMap(pattern => {
    const expression = new RegExp(pattern.source, `${pattern.flags.replace('g', '')}g`);
    return [...answer.matchAll(expression)].map(match => ({ value: match[0], index: match.index || 0 }));
  });
  const ranked = candidates.map(candidate => {
    const before = answer.slice(Math.max(0, candidate.index - 52), candidate.index);
    const after = answer.slice(candidate.index + candidate.value.length, candidate.index + candidate.value.length + 24);
    let score = /(?:released?|launched?|published)(?:\s+\w+){0,2}\s+(?:on\s+)?$/i.test(before)
      || /release date\s*[:\-]?\s*$/i.test(before) ? 3 : 0;
    if (candidate.index < 24 && /^\s*[-–—]/.test(after)) score -= 2;
    return { ...candidate, score };
  }).sort((left, right) => right.score - left.score || left.index - right.index);
  return ranked[0]?.score > 0 ? ranked[0].value : '';
}

export function resultSnippetFocus(query, snippet) {
  const request = String(query || '').trim();
  const answer = String(snippet || '').trim();
  if (!request || !answer) return '';
  const patterns = [];
  if (/\b(?:when|released?|release date|launch date|published)\b/i.test(request)) {
    const requestedVersions = request.match(/\bv?\d+(?:\.\d+){1,4}\b/gi) || [];
    if (requestedVersions.some(version => !new RegExp(`\\b${version.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\$&')}\\b`, 'i').test(answer))) {
      return '';
    }
    const date = bestResultDateFocus(answer);
    return date || '';
  }
  if (/\b(?:latest|version|release)\b/i.test(request)) {
    patterns.push(/\bv?\d+(?:\.\d+){1,4}(?:[-+][a-z0-9.-]+)?\b/i);
  }
  if (/\b(?:price|cost|how much)\b/i.test(request)) {
    patterns.push(/(?:[$€£¥₹]\s?\d[\d,.]*|\d[\d,.]*\s?(?:usd|cad|eur|gbp|jpy|cny))\b/i);
  }
  if (/\b(?:percent|percentage|rate)\b/i.test(request)) patterns.push(/\b\d+(?:\.\d+)?%/);
  for (const pattern of patterns) {
    const match = answer.match(pattern)?.[0] || '';
    if (!match) continue;
    if (/^v?\d+(?:\.\d+){1,4}/i.test(match)
      && request.toLocaleLowerCase().includes(match.toLocaleLowerCase())) continue;
    return match;
  }
  return '';
}

function renderResultSnippet(node, snippet, query) {
  const value = String(snippet || '');
  const focus = resultSnippetFocus(query, value);
  const parts = answerFocusParts(value, focus);
  if (!parts) {
    node.textContent = value;
    return;
  }
  const marker = document.createElement('mark');
  marker.className = 'andromeda-result-focus';
  marker.textContent = parts.focus;
  node.append(document.createTextNode(parts.before), marker, document.createTextNode(parts.after));
}

export function formatPublishedDate(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    const dateOnly = new Date(`${raw}T12:00:00Z`);
    if (Number.isNaN(dateOnly.getTime()) || dateOnly.toISOString().slice(0, 10) !== raw) return raw;
    return formatDate(dateOnly, {
      year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC',
    });
  }
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return formatDateTime(parsed, {
    year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

function resultNode(result) {
  const row = document.createElement('article');
  row.className = 'andromeda-result';
  const body = document.createElement('div');
  const source = document.createElement('div');
  source.className = 'andromeda-result-source';
  source.appendChild(mediaFrame(result, { favicon: true }));
  const sourceCopy = document.createElement('span');
  sourceCopy.className = 'andromeda-source-copy';
  const sourceName = document.createElement('span');
  sourceName.className = 'andromeda-source-name';
  sourceName.textContent = (result.publisher || safeUrl(result.url)?.hostname || 'web').replace(/^www\./, '');
  const site = document.createElement('span');
  site.className = 'andromeda-result-site';
  site.textContent = safeUrl(result.url)?.href.replace(/^https?:\/\//, '').replace(/\/$/, '') || '';
  sourceCopy.append(sourceName, site);
  source.appendChild(sourceCopy);
  const link = makeExternalLink(result, 'andromeda-result-title');
  const snippet = document.createElement('p');
  renderResultSnippet(snippet, result.snippet, _state.query);
  body.append(source, link, snippet);
  row.append(body);
  return row;
}

function imageNode(result) {
  const card = makeExternalLink(result, 'andromeda-image-card');
  card.textContent = '';
  card.appendChild(mediaFrame(result));
  const title = document.createElement('span');
  title.className = 'andromeda-media-title';
  title.textContent = result.title || tr('andromeda.image_result');
  const meta = document.createElement('span');
  meta.className = 'andromeda-media-meta';
  meta.textContent = result.publisher || safeUrl(result.url)?.hostname || '';
  card.append(title, meta);
  return card;
}

function newsNode(result) {
  const card = document.createElement('article');
  card.className = `andromeda-news-card${result.thumbnail_url || result.image_url ? '' : ' no-media'}`;
  const copy = document.createElement('div');
  const source = document.createElement('span');
  source.className = 'andromeda-news-source';
  source.textContent = result.publisher || safeUrl(result.url)?.hostname || 'web';
  const link = makeExternalLink(result, 'andromeda-news-title');
  const snippet = document.createElement('p');
  snippet.textContent = result.snippet || tr('andromeda.no_description');
  const date = document.createElement('span');
  date.className = 'andromeda-news-date';
  date.textContent = formatPublishedDate(result.published);
  const meta = document.createElement('div');
  meta.className = 'andromeda-news-meta';
  if (date.textContent) meta.appendChild(date);
  const href = safeUrl(result.url);
  if (href) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'andromeda-news-save';
    button.textContent = tr('andromeda.save_library');
    button.setAttribute('aria-label', tr('andromeda.save_story', { title: result.title || tr('andromeda.this_story') }));
    button.addEventListener('click', async () => {
      button.disabled = true;
      button.textContent = tr('common.saving');
      try {
        const saved = await jsonRequest('/api/read/save-news', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            url: href.href,
            title: result.title || '',
            excerpt: result.snippet || '',
            publisher: result.publisher || href.hostname,
            image_url: result.thumbnail_url || result.image_url || '',
          }),
        });
        button.textContent = saved.duplicate ? tr('andromeda.already_library') : tr('andromeda.saved_library');
        button.dataset.saved = 'true';
      } catch (error) {
        button.disabled = false;
        button.textContent = tr('andromeda.retry_save');
        status(error.message || tr('andromeda.save_failed'));
      }
    });
    meta.appendChild(button);
  }
  copy.append(source, link);
  if (result.snippet) copy.appendChild(snippet);
  if (meta.childElementCount) copy.appendChild(meta);
  card.appendChild(copy);
  if (result.thumbnail_url || result.image_url) card.appendChild(mediaFrame(result));
  return card;
}

function videoNode(result) {
  const card = makeExternalLink(result, 'andromeda-video-card');
  card.textContent = '';
  card.appendChild(mediaFrame(result, { video: true }));
  const title = document.createElement('span');
  title.className = 'andromeda-media-title';
  title.textContent = result.title || tr('andromeda.video_result');
  const meta = document.createElement('span');
  meta.className = 'andromeda-media-meta';
  meta.textContent = [result.publisher || safeUrl(result.url)?.hostname, formatPublishedDate(result.published)].filter(Boolean).join(' · ');
  card.append(title, meta);
  return card;
}

function emptyMessage(state, currentCategory) {
  const categoryLabel = tr(`andromeda.category.${currentCategory}`);
  if (state === 'disabled') return tr('andromeda.results_disabled');
  if (state === 'loading') return tr('andromeda.finding_results', { category: categoryLabel });
  if (state === 'error') return tr('andromeda.search_error');
  if (state === 'offline') return tr('andromeda.offline');
  return tr('andromeda.no_results', { category: categoryLabel });
}

export function renderAndromedaResults(results, state = 'ready', currentCategory = category()) {
  _state.resultStatus = state;
  const targets = {
    all: el('andromeda-results'), images: el('andromeda-images'),
    news: el('andromeda-news'), videos: el('andromeda-videos'),
  };
  const list = targets[currentCategory];
  if (!list) return;
  list.replaceChildren();
  if (state === 'loading' && currentCategory === 'images') {
    for (let index = 0; index < 15; index += 1) {
      const skeleton = document.createElement('span');
      skeleton.className = 'andromeda-image-skeleton';
      skeleton.setAttribute('aria-hidden', 'true');
      list.appendChild(skeleton);
    }
  }
  const render = { all: resultNode, images: imageNode, news: newsNode, videos: videoNode }[currentCategory];
  for (const result of results || []) list.appendChild(render(result));
  if (!results?.length && !(state === 'loading' && currentCategory === 'images')) {
    const empty = document.createElement('div');
    empty.className = 'andromeda-empty';
    empty.textContent = emptyMessage(state, currentCategory);
    list.appendChild(empty);
  }
  const actions = el('andromeda-actions');
  if (actions) actions.hidden = !_state.rawQuery || currentCategory !== 'all';
  const tail = el('andromeda-results-tail');
  if (tail) tail.hidden = true;
}

export function canLoadMoreResults(currentCategory, count, hasMore, requestedMax = 0) {
  const reachedNormalCap = Math.max(count, Number.parseInt(requestedMax, 10) || 0) >= 20;
  return Boolean(hasMore) && (currentCategory !== 'all' || !reachedNormalCap);
}

export function canReplacePageResults(result = {}, currentCount = 0) {
  return result.status !== 'error'
    && Array.isArray(result.results)
    && result.results.length >= currentCount;
}

export function mergePageResults(current = [], incoming = []) {
  const merged = [];
  const seen = new Set();
  for (const row of [...current, ...incoming]) {
    const key = String(row?.url || row?.link || row?.image_url || JSON.stringify(row));
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(row);
  }
  return merged;
}

function updateMoreResults(hasMore = _state.hasMore) {
  const tail = el('andromeda-results-tail');
  const button = el('andromeda-more-results');
  if (!tail || !button) return;
  const count = _state.results.length;
  const canGrow = canLoadMoreResults(
    category(), count, hasMore, _state.request?.max_results,
  );
  tail.hidden = !(count > 0 && canGrow);
  button.hidden = tail.hidden;
  button.disabled = false;
  button.textContent = tr('andromeda.more_results');
}

function appendImageSkeletons(count = 6) {
  const list = el('andromeda-images');
  if (!list || category() !== 'images') return;
  for (let index = 0; index < count; index += 1) {
    const skeleton = document.createElement('span');
    skeleton.className = 'andromeda-image-skeleton page-skeleton';
    skeleton.setAttribute('aria-hidden', 'true');
    list.appendChild(skeleton);
  }
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
  const toggle = el('andromeda-evidence-toggle');
  if (toggle) toggle.hidden = !_state.evidence.length;
}

function citationNodes(claim) {
  const refs = document.createElement('span');
  refs.className = 'andromeda-citations';
  (claim.citations || []).forEach((citation, index) => {
    const link = document.createElement('a');
    link.className = 'andromeda-citation';
    link.href = safeUrl(citation.url)?.href || '#andromeda-evidence';
    link.target = safeUrl(citation.url) ? '_blank' : '';
    link.rel = safeUrl(citation.url) ? 'noopener noreferrer' : '';
    link.textContent = String(index + 1);
    link.setAttribute('aria-label', `source ${index + 1}: ${citation.title || 'citation'}`);
    refs.appendChild(link);
  });
  return refs;
}

function renderKeyAnswer(claim) {
  const key = el('andromeda-key-answer');
  const value = el('andromeda-key-answer-text');
  if (!key || !value) return;
  key.hidden = false;
  value.replaceChildren();
  const parts = answerFocusParts(claim.text, claim.focus);
  if (parts) {
    const marker = document.createElement('mark');
    marker.className = 'andromeda-marker';
    marker.textContent = parts.focus;
    value.append(document.createTextNode(parts.before), marker, document.createTextNode(parts.after));
  } else {
    value.append(document.createTextNode(claim.text || ''));
  }
  value.append(citationNodes(claim));
}

export function answerFocusParts(text, focus) {
  const answer = String(text || '');
  const requested = String(focus || '').trim();
  if (!answer || !requested) return null;
  const start = answer.toLocaleLowerCase().indexOf(requested.toLocaleLowerCase());
  if (start < 0) return null;
  return {
    before: answer.slice(0, start),
    focus: answer.slice(start, start + requested.length),
    after: answer.slice(start + requested.length),
  };
}

function renderContextClaim(claim, index) {
  const list = el('andromeda-claims');
  if (!list) return;
  const node = document.createElement('p');
  node.className = 'andromeda-claim';
  node.append(document.createTextNode(claim.text || ''), citationNodes(claim));
  node.dataset.claim = String(index);
  list.appendChild(node);
}

function renderClaim(claim, index) {
  renderContextClaim(claim, index);
}

export function contextClaimsForOverview(overview = {}) {
  const claims = Array.isArray(overview.claims) ? overview.claims : [];
  const sourceIndex = Number.isInteger(overview.key_answer?.source_claim_index)
    ? overview.key_answer.source_claim_index
    : -1;
  return claims.filter((_claim, index) => index !== sourceIndex);
}

function renderCompleteOverview(overview) {
  _state.overview = overview || {};
  el('andromeda-claims')?.replaceChildren();
  const key = el('andromeda-key-answer');
  if (key) key.hidden = true;
  const claims = _state.overview.claims || [];
  const keyAnswer = _state.overview.key_answer?.text ? _state.overview.key_answer : null;
  if (keyAnswer) renderKeyAnswer(keyAnswer);
  const contextClaims = keyAnswer ? contextClaimsForOverview(_state.overview) : claims;
  contextClaims.forEach((claim, index) => renderContextClaim(claim, index));
  const freshness = _state.overview.freshness || {};
  const checked = freshness.checked_on ? ` · ${tr('andromeda.checked_on', { date: freshness.checked_on })}` : '';
  if (_state.overview.status === 'ready') {
    text('andromeda-overview-state', `${tr('andromeda.checked_sources')}${checked}`);
    showRecovery(false);
  } else {
    text('andromeda-overview-state', `${tr('andromeda.insufficient_evidence')}${checked}`);
    showRecovery(true, 'insufficient_evidence');
  }
}

function verificationToday() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function clearVerificationView() {
  const root = el('andromeda-verification');
  if (root) root.hidden = true;
  text('andromeda-verification-state', '');
  const retry = el('andromeda-verification-retry');
  if (retry) retry.hidden = true;
  const toggle = el('andromeda-verification-details-toggle');
  if (toggle) {
    toggle.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
  }
  const details = el('andromeda-verification-details');
  if (details) {
    details.hidden = true;
    details.replaceChildren();
  }
}

function renderVerification(verification = {}, { saved = false } = {}) {
  _state.verification = verification || {};
  const root = el('andromeda-verification');
  if (!root) return;
  root.hidden = false;
  const retry = el('andromeda-verification-retry');
  const toggle = el('andromeda-verification-details-toggle');
  const details = el('andromeda-verification-details');
  if (retry) retry.hidden = true;
  if (toggle) {
    toggle.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
  }
  if (details) {
    details.hidden = true;
    details.replaceChildren();
  }
  const state = verification.status || 'skipped';
  if (state === 'pending' || state === 'running') {
    text('andromeda-verification-state', 'checking independently…');
    return;
  }
  if (state !== 'checked') {
    text('andromeda-verification-state', state === 'cancelled'
      ? 'independent check cancelled'
      : 'not independently checked');
    if (retry) retry.hidden = false;
    return;
  }
  const result = verification.result || verification;
  const counts = result.counts || {};
  const checkedOn = result.checked_on || String(verification.checked_at || '').slice(0, 10);
  const freshness = checkedOn === verificationToday() ? 'checked today' : `checked ${checkedOn || 'earlier'}`;
  const parts = [freshness];
  if (counts.verified) parts.push(`${counts.verified} ${counts.verified === 1 ? 'claim' : 'claims'} verified`);
  if (counts.corrected) parts.push('corrected after verification', `${counts.corrected} ${counts.corrected === 1 ? 'claim' : 'claims'} corrected`);
  if (counts.conflicting || result.source_conflicts) parts.push('sources conflict');
  if (counts.insufficient) parts.push(`${counts.insufficient} unresolved`);
  if (saved && checkedOn !== verificationToday()) parts.push('saved result');
  text('andromeda-verification-state', parts.join(' · '));
  if (retry) retry.hidden = false;
  const changes = Array.isArray(result.changes) ? result.changes : [];
  if (!changes.length || !details || !toggle) return;
  for (const change of changes) {
    const item = document.createElement('div');
    const before = document.createElement('span');
    const after = document.createElement('strong');
    before.textContent = `was: ${change.before || ''}`;
    after.textContent = `now: ${change.after || ''}`;
    item.append(before, after);
    details.appendChild(item);
  }
  toggle.hidden = false;
}

function applyVerifiedCorrections(result = {}) {
  const corrected = Array.isArray(result.corrected_claims) ? result.corrected_claims : [];
  if (!corrected.length) return;
  const next = { ..._state.overview, claims: corrected };
  const sourceIndex = Number.isInteger(next.key_answer?.source_claim_index)
    ? next.key_answer.source_claim_index
    : -1;
  const correctedKey = corrected[sourceIndex];
  if (correctedKey?.text) next.key_answer = { ...next.key_answer, text: correctedKey.text };
  renderCompleteOverview(next);
}

async function cancelVerification() {
  clearTimeout(_verificationPollTimer);
  _verificationPollTimer = 0;
  const jobId = _verificationJobId;
  _verificationJobId = '';
  if (!jobId) return;
  try { await jsonRequest(`/api/andromeda/verification/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' }); }
  catch {}
}

async function pollVerification(jobId, searchGeneration) {
  if (!jobId || jobId !== _verificationJobId || searchGeneration !== _searchGeneration) return;
  try {
    const job = await jsonRequest(`/api/andromeda/verification/${encodeURIComponent(jobId)}`);
    if (jobId !== _verificationJobId || searchGeneration !== _searchGeneration) return;
    _state.verifierModel = job.model || _state.verifierModel;
    renderVerification(job);
    if (job.status === 'pending' || job.status === 'running') {
      _verificationPollTimer = window.setTimeout(() => pollVerification(jobId, searchGeneration), 850);
      return;
    }
    _verificationJobId = '';
    if (job.status === 'checked') applyVerifiedCorrections(job.result || {});
  } catch {
    if (jobId !== _verificationJobId || searchGeneration !== _searchGeneration) return;
    _verificationJobId = '';
    renderVerification({ status: 'failed' });
  }
}

async function startVerification(query, answer, results, searchGeneration, { manual = false } = {}) {
  await cancelVerification();
  if (searchGeneration !== _searchGeneration) return;
  clearVerificationView();
  let preview;
  try {
    preview = await jsonRequest('/api/andromeda/verification/preview', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query, manual }),
    });
  } catch {
    renderVerification({ status: 'failed' });
    return;
  }
  if (searchGeneration !== _searchGeneration) return;
  if (preview.status === 'skipped') {
    renderVerification(preview);
    return;
  }
  const model = preview.model || {};
  _state.verifierModel = model;
  const confirmation = {};
  if (model.privacy_class === 'remote') {
    const allowed = await confirmDialog(
      `independent fact-check: send this query, answer, and source evidence to ${model.endpoint} · ${model.model}?`,
    );
    if (searchGeneration !== _searchGeneration) return;
    if (!allowed) {
      renderVerification({ status: 'cancelled' });
      return;
    }
    confirmation.confirmed_endpoint_id = model.endpoint_id;
    confirmation.confirmed_model = model.model;
  }
  renderVerification({ status: 'pending' });
  try {
    const job = await jsonRequest('/api/andromeda/verification', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query, answer, results, manual, ...confirmation }),
    });
    if (searchGeneration !== _searchGeneration) {
      if (job.id) {
        try { await jsonRequest(`/api/andromeda/verification/${encodeURIComponent(job.id)}/cancel`, { method: 'POST' }); }
        catch {}
      }
      return;
    }
    if (job.status === 'skipped') {
      renderVerification(job);
      return;
    }
    _verificationJobId = job.id || '';
    _state.verifierModel = job.model || model;
    renderVerification(job);
    if (_verificationJobId) await pollVerification(_verificationJobId, searchGeneration);
  } catch {
    renderVerification({ status: 'failed' });
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
  return _modelChoices.get(providerValue('andromeda-exact-model')) || {};
}

async function previewOverview() {
  const params = new URLSearchParams({ band: providerValue('andromeda-band', 'standard') });
  const exact = selectedExactModel();
  if (exact.endpoint_id) {
    params.set('endpoint_id', exact.endpoint_id);
    params.set('model', exact.model);
  }
  return jsonRequest(`/api/andromeda/overview/preview?${params}`);
}

async function startOverview(query, results, searchGeneration) {
  showOverview(true);
  clearOverview(tr('andromeda.checking_sources'));
  const stop = el('andromeda-cancel-overview');
  if (stop) stop.hidden = false;
  let preview;
  try {
    preview = await previewOverview();
  } catch (error) {
    if (searchGeneration !== _searchGeneration) return;
    text('andromeda-overview-state', failureMessage(tr('andromeda.links_available', { error: error.message }), error));
    showRecovery(true, error.code);
    if (stop) stop.hidden = true;
    return;
  }
  if (searchGeneration !== _searchGeneration) return;
  _state.model = preview;
  text('andromeda-model', `${preview.model} · ${preview.endpoint} · ${preview.privacy_class}`);
  const confirmation = {};
  if (preview.privacy_class === 'remote') {
    const allowed = await confirmDialog(tr('andromeda.remote_confirm', { endpoint: preview.endpoint, model: preview.model }));
    if (searchGeneration !== _searchGeneration) return;
    if (!allowed) {
      text('andromeda-overview-state', tr('andromeda.cancelled_unsent'));
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
  try {
    const response = await fetch('/api/andromeda/overview', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      signal: _overviewAbort.signal,
      body: JSON.stringify({
        query, results, band: providerValue('andromeda-band', 'standard'),
        endpoint_id: exact.endpoint_id || '', model: exact.model || '', ...confirmation,
      }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw Object.assign(new Error(body.detail || tr('andromeda.overview_failed')), body);
    }
    text('andromeda-overview-state', tr('andromeda.reading_sources'));
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let claimIndex = 0;
    while (true) {
      const { value, done } = await reader.read();
      if (searchGeneration !== _searchGeneration) {
        await reader.cancel();
        return;
      }
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
          text('andromeda-overview-state', failureMessage(event.detail || tr('andromeda.overview_links_remain'), event));
          showRecovery(true, event.code);
        }
      }
      if (done) break;
    }
    if (searchGeneration === _searchGeneration && _state.overview?.status === 'ready') {
      void startVerification(query, _state.overview, results, searchGeneration);
    }
  } catch (error) {
    if (searchGeneration !== _searchGeneration) return;
    const message = error.name === 'AbortError'
      ? tr('andromeda.overview_stopped')
      : tr('andromeda.overview_failed_links', { error: error.message || tr('andromeda.overview_failed') });
    text('andromeda-overview-state', failureMessage(message, error));
    showRecovery(true, error.name === 'AbortError' ? 'cancelled' : error.code || 'overview_failed');
  } finally {
    if (searchGeneration === _searchGeneration && stop) stop.hidden = true;
  }
}

export async function runAndromedaSearch(queryValue = '', options = {}) {
  const input = el('andromeda-query');
  const query = String(queryValue || input?.value || '').trim();
  if (!query) { input?.focus(); return; }
  const currentCategory = CATEGORIES.has(options.category) ? options.category : category();
  if (input) input.value = query;
  setPageState('results');
  el('andromeda-result-tools').hidden = false;
  setCategory(currentCategory, { search: false });
  _searchAbort?.abort();
  _overviewAbort?.abort();
  void cancelVerification();
  const searchGeneration = ++_searchGeneration;
  _searchAbort = new AbortController();
  _state = {
    ...freshState(),
    rawQuery: query,
    query: queryWithNoAi(query, /(^|\s)!ai(?=\s|$)/i.test(query)),
    category: currentCategory,
    documentScope: options.documentScope || null,
    usedNoAi: /(^|\s)!ai(?=\s|$)/i.test(query),
  };
  renderAndromedaResults([], 'loading', currentCategory);
  clearOverview();
  clearVerificationView();
  const wantsOverview = currentCategory === 'all'
    && pressed('andromeda-overview-toggle')
    && !/(^|\s)!ai(?=\s|$)/i.test(query);
  showOverview(wantsOverview);
  status(tr('andromeda.searching'));
  const request = {
    query,
    category: currentCategory,
    provider: providerValue('andromeda-provider'),
    normal_results: pressed('andromeda-results-toggle'),
    overview: wantsOverview,
    max_results: pageSize(currentCategory),
  };
  _state.request = { ...request, band: providerValue('andromeda-band', 'standard') };
  try {
    const result = await jsonRequest('/api/andromeda/search', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      signal: _searchAbort.signal, body: JSON.stringify(request),
    });
    if (searchGeneration !== _searchGeneration) return;
    _state.usedNoAi = !!result.used_no_ai;
    _state.query = queryWithNoAi(result.query || query, _state.usedNoAi);
    _state.results = result.results || [];
    _state.hasMore = !!result.has_more;
    _state.overviewSeed = result.overview_seed || _state.results;
    if (input) input.value = _state.query;
    renderAndromedaResults(_state.results, result.status, currentCategory);
    updateMoreResults();
    text('andromeda-result-meta', result.normal_results_enabled
      ? [trp('andromeda.result_count', _state.results.length), result.provider || tr('andromeda.provider'), `${result.elapsed_ms} ms`].filter(Boolean).join(' · ')
      : tr('andromeda.normal_hidden'));
    if (result.status === 'partial') status(tr('andromeda.partial_sources'));
    else if (result.status === 'error') status(failureMessage(tr('andromeda.search_failed'), result));
    else status('');
    if (currentCategory === 'all' && result.overview_requested && _state.overviewSeed.length) {
      await startOverview(result.query, _state.overviewSeed, searchGeneration);
    } else if (currentCategory === 'all' && result.status === 'error' && result.overview_requested) {
      showOverview(true);
      text('andromeda-overview-state', failureMessage(tr('andromeda.no_overview_sources'), result));
      showRecovery(true, result.failure_type || 'search_failed');
    } else if (currentCategory === 'all' && result.overview_requested) {
      showOverview(true);
      text('andromeda-overview-state', tr('andromeda.no_safe_sources'));
      showRecovery(true, 'no_sources');
    } else {
      showOverview(false);
    }
  } catch (error) {
    if (searchGeneration !== _searchGeneration || error.name === 'AbortError') return;
    renderAndromedaResults([], navigator.onLine === false ? 'offline' : 'error', currentCategory);
    status(failureMessage(error.message || tr('andromeda.search_failed'), error));
    showOverview(false);
  }
}

async function loadMoreResults() {
  const button = el('andromeda-more-results');
  if (!button || !_state.rawQuery) return;
  const currentCategory = category();
  const searchGeneration = _searchGeneration;
  const increment = currentCategory === 'all' ? Math.max(5, pageSize('all')) : PAGE_SIZES[currentCategory];
  const previousMax = Math.max(
    pageSize(currentCategory),
    Number.parseInt(_state.request?.max_results, 10) || 0,
  );
  if (currentCategory === 'all' && previousMax >= 20) {
    updateMoreResults();
    return;
  }
  const nextMax = currentCategory === 'all'
    ? Math.min(20, previousMax + increment)
    : previousMax + increment;
  button.disabled = true;
  button.textContent = tr('common.loading');
  appendImageSkeletons();
  _searchAbort?.abort();
  _searchAbort = new AbortController();
  try {
    const request = {
      ..._state.request,
      query: _state.rawQuery,
      category: currentCategory,
      overview: false,
      max_results: nextMax,
    };
    const result = await jsonRequest('/api/andromeda/search', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      signal: _searchAbort.signal, body: JSON.stringify(request),
    });
    if (searchGeneration !== _searchGeneration) return;
    if (!canReplacePageResults(result, _state.results.length)) {
      document.querySelectorAll('.andromeda-image-skeleton.page-skeleton').forEach(node => node.remove());
      status(failureMessage(tr('andromeda.more_failed'), result));
      updateMoreResults();
      return;
    }
    _state.results = mergePageResults(_state.results, result.results);
    _state.hasMore = !!result.has_more;
    _state.request = { ..._state.request, max_results: nextMax };
    renderAndromedaResults(_state.results, result.status, currentCategory);
    updateMoreResults();
    text('andromeda-result-meta', [
      trp('andromeda.result_count', _state.results.length),
      result.provider || tr('andromeda.provider'), `${result.elapsed_ms} ms`,
    ].filter(Boolean).join(' · '));
    status(result.status === 'partial' ? tr('andromeda.partial_sources') : '');
  } catch (error) {
    if (searchGeneration !== _searchGeneration || error.name === 'AbortError') return;
    document.querySelectorAll('.andromeda-image-skeleton.page-skeleton').forEach(node => node.remove());
    status(failureMessage(error.message || tr('andromeda.more_failed'), error));
    updateMoreResults();
  }
}

async function saveCurrent() {
  if (!_state.rawQuery) return;
  try {
    await jsonRequest('/api/andromeda/saved', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        query: _state.rawQuery,
        request: { ..._state.request, query: _state.rawQuery, has_more: _state.hasMore },
        results: _state.results,
        overview: _state.overview, evidence: _state.evidence, model: _state.model,
        verification: _state.verification, verifier_model: _state.verifierModel,
      }),
    });
    status(tr('andromeda.search_saved'));
    await loadSaved();
  } catch (error) { status(error.message); }
}

function reopen(saved) {
  const overviewPreference = pressed('andromeda-overview-toggle');
  _searchAbort?.abort();
  _overviewAbort?.abort();
  void cancelVerification();
  _searchAbort = null;
  _overviewAbort = null;
  _searchGeneration += 1;
  const savedCategory = CATEGORIES.has(saved.request?.category) ? saved.request.category : 'all';
  const savedRawQuery = String(saved.request?.query || saved.query || '').trim();
  const savedUsedNoAi = /(^|\s)!ai(?=\s|$)/i.test(savedRawQuery);
  _state = {
    rawQuery: savedRawQuery,
    query: queryWithNoAi(savedRawQuery, savedUsedNoAi),
    category: savedCategory,
    request: { ...(saved.request || {}), query: savedRawQuery },
    results: saved.results || [],
    overviewSeed: saved.results || [], overview: saved.overview || {},
    evidence: saved.evidence || [], model: saved.model || {},
    verification: saved.verification || {}, verifierModel: saved.verifier_model || {},
    hasMore: saved.request?.has_more === true,
    usedNoAi: savedUsedNoAi,
  };
  setPageState('results');
  el('andromeda-result-tools').hidden = false;
  if (el('andromeda-query')) {
    el('andromeda-query').value = _state.query;
  }
  setCategory(savedCategory, { search: false });
  setPressed('andromeda-results-toggle', saved.request?.normal_results !== false);
  setPressed(
    'andromeda-overview-toggle',
    savedCategory === 'all' && !_state.usedNoAi
      ? saved.request?.overview !== false
      : overviewPreference,
  );
  setDropdownValue(el('andromeda-provider'), saved.request?.provider || '');
  setDropdownValue(el('andromeda-band'), saved.request?.band || 'standard');
  renderAndromedaResults(_state.results, _state.results.length ? 'ready' : 'empty', savedCategory);
  updateMoreResults();
  renderEvidence(_state.evidence);
  showOverview(savedCategory === 'all' && !!Object.keys(_state.overview).length);
  if (_state.overview?.status) renderCompleteOverview(_state.overview);
  if (Object.keys(_state.verification).length) renderVerification(_state.verification, { saved: true });
  else clearVerificationView();
  text('andromeda-model', [_state.model.model, _state.model.endpoint].filter(Boolean).join(' · '));
  text('andromeda-result-meta', tr('andromeda.saved_checked', { date: saved.checked_at || '' }));
  status(tr('andromeda.saved_reopened'));
  closeSettings();
}

async function loadSaved() {
  const list = el('andromeda-saved-list');
  if (!list) return;
  list.replaceChildren();
  try {
    const { searches } = await jsonRequest('/api/andromeda/saved');
    if (!searches.length) { list.textContent = tr('andromeda.nothing_saved'); return; }
    for (const item of searches) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'andromeda-saved-row';
      button.textContent = item.query;
      button.title = tr('andromeda.checked_on', { date: item.checked_at });
      button.addEventListener('click', async () => {
        try { reopen(await jsonRequest(`/api/andromeda/saved/${item.id}`)); }
        catch (error) { status(error.message); }
      });
      list.appendChild(button);
    }
  } catch { list.textContent = tr('andromeda.saved_unavailable'); }
}

async function loadModelChoices() {
  const control = el('andromeda-exact-model');
  if (!control) return;
  const options = [{ value: '', label: 'band default' }];
  _modelChoices = new Map();
  try {
    const endpoints = await jsonRequest('/api/models');
    let index = 0;
    for (const endpoint of endpoints) {
      for (const model of endpoint.models || []) {
        const key = String(++index);
        _modelChoices.set(key, { endpoint_id: endpoint.id, model });
        options.push({ value: key, label: `${model} · ${endpoint.name}` });
      }
    }
  } catch {}
  populateDropdown(control, options, '');
}

async function loadProviderChoices(requestedConfigurationGeneration = null) {
  const control = el('andromeda-provider');
  if (!control) return;
  const selectedProvider = providerValue('andromeda-provider');
  const options = [{ value: '', label: 'automatic' }];
  try {
    const response = await jsonRequest('/api/andromeda/providers');
    for (const provider of response.providers || []) {
      if (provider.available) options.push({ value: provider.value, label: provider.label });
    }
  } catch (error) {
    if (requestedConfigurationGeneration !== null
      && requestedConfigurationGeneration !== _searchConfigurationGeneration) return;
    setSearchSettingsStatus(error.message || 'search providers unavailable', true);
    return;
  }
  if (requestedConfigurationGeneration !== null
    && requestedConfigurationGeneration !== _searchConfigurationGeneration) return;
  const preservedProvider = options.some(option => option.value === selectedProvider)
    ? selectedProvider
    : '';
  populateDropdown(control, options, preservedProvider);
}

async function explainResults() {
  const links = _state.results.map(result => safeUrl(result.url)?.href || '').filter(Boolean);
  if (!links.length) { status(tr('andromeda.no_web_results')); return; }
  const request = `Explain these search results using only their contents. Cite each link and say when evidence is missing:\n${links.join('\n')}`;
  if (typeof window._askInChat !== 'function') {
    status(tr('andromeda.aide_unavailable'));
    return;
  }
  try {
    const projectId = validatedProjectId(
      new URLSearchParams(location.search).get('project_id'),
    );
    await window._askInChat(request, false, _state.documentScope, projectId);
  } catch (error) {
    status(error?.message || tr('andromeda.aide_failed'));
  }
}

function bindRecovery() {
  el('andromeda-recovery')?.addEventListener('click', event => {
    const action = event.target.closest('[data-andromeda-recovery]')?.dataset.andromedaRecovery;
    if (action === 'retry') runAndromedaSearch();
    if (action === 'broaden') {
      const broad = (el('andromeda-query')?.value || '')
        .replace(/"([^"]+)"/g, '$1').replace(/(^|\s)![^\s]+/g, ' ').replace(/\s+/g, ' ').trim();
      runAndromedaSearch(broad);
    }
    if (action === 'edit') el('andromeda-query')?.focus();
    if (action === 'results') el('andromeda-results-title')?.scrollIntoView({ block: 'start' });
  });
}

function settingsOpen() { return !el('andromeda-settings-panel')?.hidden; }

const SEARCH_PROVIDER_LABELS = Object.freeze({
  duckduckgo: 'duckduckgo', tavily: 'tavily', brave: 'brave', searxng: 'searxng',
  google_pse: 'google pse', serper: 'serper', disabled: 'disabled', none: 'stop',
});

const SEARCH_SECRET_SETTINGS = new Set([
  'tavily_api_key', 'brave_api_key', 'google_pse_api_key', 'serper_api_key',
]);

export function sanitizeSearchSettings(settings = {}) {
  return Object.fromEntries(
    Object.entries(settings).filter(([key]) => !SEARCH_SECRET_SETTINGS.has(key)),
  );
}

function providerValue(id, fallback = '') {
  return el(id)?.value || el(id)?.dataset?.value || fallback;
}

function setSearchSettingsStatus(message = '', error = false) {
  const node = el('andromeda-search-settings-status');
  if (!node) return;
  node.textContent = message;
  node.dataset.error = error ? 'true' : 'false';
}

async function patchSearchSettings(patch, message = 'saved') {
  try {
    const settings = await jsonRequest('/api/settings', {
      method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(patch),
    });
    _settingsState = {
      ...sanitizeSearchSettings(_settingsState),
      ...sanitizeSearchSettings(patch),
      ...sanitizeSearchSettings(settings),
    };
    setSearchSettingsStatus(message);
    return sanitizeSearchSettings(settings);
  } catch (error) {
    setSearchSettingsStatus(error.message || 'settings could not be saved', true);
    throw error;
  }
}

function updateProviderSettingsSummary() {
  const primary = providerValue('andromeda-primary-provider', 'duckduckgo');
  const fallback = providerValue('andromeda-fallback-provider', 'none');
  const primaryLabel = SEARCH_PROVIDER_LABELS[primary] || primary;
  const hasFallback = fallback && !['none', 'disabled', primary].includes(fallback);
  const fallbackLabel = SEARCH_PROVIDER_LABELS[fallback] || fallback;
  text('andromeda-provider-order', hasFallback ? `${primaryLabel} → ${fallbackLabel}` : primaryLabel);
  const selected = [...new Set([primary, fallback].filter(value => value && !['none', 'disabled'].includes(value)))];
  const fields = [...document.querySelectorAll('[data-andromeda-provider-field]')];
  let visibleFields = 0;
  fields.forEach(row => {
    row.hidden = !selected.includes(row.dataset.andromedaProviderField);
    if (!row.hidden) visibleFields += 1;
  });
  const container = el('andromeda-provider-fields');
  if (container) container.hidden = visibleFields === 0;
}

function configuredPlaceholder(id, configured, emptyText = 'not configured') {
  const input = el(id);
  if (input) input.placeholder = configured ? 'configured — enter a replacement' : emptyText;
}

function setCredentialClearState(inputId, configured) {
  const button = document.querySelector(`[data-andromeda-clear-setting="${inputId}"]`);
  if (button) button.disabled = !configured;
}

async function loadSearchConfiguration() {
  const requestedGeneration = _searchConfigurationGeneration;
  try {
    await _searchConfigurationWrite.catch(() => {});
    if (requestedGeneration !== _searchConfigurationGeneration) return null;
    const current = await jsonRequest('/api/settings');
    if (requestedGeneration !== _searchConfigurationGeneration) return null;
    _settingsState = current;
    const primary = current.search_provider || 'duckduckgo';
    const fallback = [current.search_fallback, ...(current.search_fallback_chain || [])]
      .find(value => value && value !== 'none' && value !== primary) || 'none';
    setDropdownValue(el('andromeda-primary-provider'), primary);
    setDropdownValue(el('andromeda-fallback-provider'), fallback);
    setDropdownValue(el('andromeda-result-count'), String(current.search_result_count || 8));
    setPressed('andromeda-verification-toggle', current.andromeda_verification_enabled !== false);
    setDropdownValue(el('andromeda-verifier-mode'), current.andromeda_verifier_mode || 'freshness-sensitive');
    configuredPlaceholder('andromeda-tavily-key', current.tavily_api_key_configured);
    configuredPlaceholder('andromeda-brave-key', current.brave_api_key_configured);
    configuredPlaceholder('andromeda-google-key', current.google_pse_api_key_configured);
    configuredPlaceholder('andromeda-serper-key', current.serper_api_key_configured);
    setCredentialClearState('andromeda-tavily-key', current.tavily_api_key_configured);
    setCredentialClearState('andromeda-brave-key', current.brave_api_key_configured);
    setCredentialClearState('andromeda-google-key', current.google_pse_api_key_configured);
    setCredentialClearState('andromeda-serper-key', current.serper_api_key_configured);
    const searxng = el('andromeda-searxng-url');
    if (searxng) searxng.placeholder = current.searxng_url || 'https://search.example.com';
    setCredentialClearState('andromeda-searxng-url', !!current.searxng_url);
    const googleCx = el('andromeda-google-cx');
    if (googleCx) googleCx.value = current.google_pse_cx || '';
    setCredentialClearState('andromeda-google-cx', !!current.google_pse_cx);
    updateProviderSettingsSummary();
    return current;
  } catch (error) {
    setSearchSettingsStatus(error.message || 'search settings unavailable', true);
    return null;
  }
}

export function configuredFallbackChain(primary, fallback) {
  if (!fallback || fallback === 'none' || fallback === 'disabled' || fallback === primary) {
    return [];
  }
  return [fallback];
}

export function queueSearchConfigurationWrite(operation) {
  const next = _searchConfigurationWrite.catch(() => {}).then(operation);
  _searchConfigurationWrite = next;
  return next;
}

async function saveSearchConfiguration() {
  const primary = providerValue('andromeda-primary-provider', 'duckduckgo');
  const selectedFallback = providerValue('andromeda-fallback-provider', 'none');
  const fallback = selectedFallback === primary ? 'none' : selectedFallback;
  const count = Number.parseInt(providerValue('andromeda-result-count', '8'), 10) || 8;
  if (fallback !== selectedFallback) {
    setDropdownValue(el('andromeda-fallback-provider'), fallback);
  }
  const fallbackChain = configuredFallbackChain(
    primary,
    fallback,
  );
  const primaryChanged = primary !== (_settingsState.search_provider || 'duckduckgo');
  const fallbackChanged = fallback !== (_settingsState.search_fallback || 'none');
  updateProviderSettingsSummary();
  const patch = {
    search_provider: primary,
    search_fallback: fallback,
    search_result_count: count,
  };
  if (primaryChanged || fallbackChanged) patch.search_fallback_chain = fallbackChain;
  const writeGeneration = ++_searchConfigurationGeneration;
  return queueSearchConfigurationWrite(async () => {
    await patchSearchSettings(patch);
    if (writeGeneration !== _searchConfigurationGeneration) return;
    await loadProviderChoices(writeGeneration);
  });
}

const SEARCH_CREDENTIAL_FIELDS = Object.freeze({
  'andromeda-tavily-key': 'tavily_api_key',
  'andromeda-brave-key': 'brave_api_key',
  'andromeda-searxng-url': 'searxng_url',
  'andromeda-google-key': 'google_pse_api_key',
  'andromeda-google-cx': 'google_pse_cx',
  'andromeda-serper-key': 'serper_api_key',
});

const _credentialWrites = new Map();
const _credentialClearPending = new Set();

export async function queueSearchCredentialWrite(setting, operation) {
  const previous = _credentialWrites.get(setting) || Promise.resolve();
  const next = previous.catch(() => {}).then(operation);
  _credentialWrites.set(setting, next);
  try {
    return await next;
  } finally {
    if (_credentialWrites.get(setting) === next) _credentialWrites.delete(setting);
  }
}

async function saveSearchCredential(input) {
  const setting = SEARCH_CREDENTIAL_FIELDS[input.id];
  const value = input.value.trim();
  if (!setting || !value || _credentialClearPending.has(input.id)) return;
  input.disabled = true;
  try {
    const label = input.closest('.andromeda-setting-field')?.querySelector('label')?.textContent
      || 'provider setting';
    await queueSearchCredentialWrite(
      setting,
      () => patchSearchSettings({ [setting]: value }, `${label} saved`),
    );
    setCredentialClearState(input.id, true);
    if (input.type === 'password') {
      input.value = '';
      input.placeholder = 'configured — enter a replacement';
    }
    await loadProviderChoices();
  } catch {} finally {
    input.disabled = false;
  }
}

async function clearSearchCredential(button) {
  const input = el(button.dataset.andromedaClearSetting);
  const setting = SEARCH_CREDENTIAL_FIELDS[input?.id];
  if (!input || !setting) return;
  _credentialClearPending.add(input.id);
  let cleared = false;
  button.disabled = true;
  input.disabled = true;
  try {
    const label = input.closest('.andromeda-setting-field')?.querySelector('label')?.textContent
      || 'provider setting';
    await queueSearchCredentialWrite(
      setting,
      () => patchSearchSettings({ [setting]: '' }, `${label} cleared`),
    );
    input.value = '';
    configuredPlaceholder(input.id, false, input.id === 'andromeda-searxng-url'
      ? 'https://search.example.com' : input.id === 'andromeda-google-cx'
        ? 'search engine id' : 'not configured');
    cleared = true;
    await loadProviderChoices();
  } catch {} finally {
    _credentialClearPending.delete(input.id);
    input.disabled = false;
    button.disabled = cleared;
  }
}

function managedSearxngState(service) {
  if (!service.support_verified && !service.installed) return 'managed install unavailable';
  if (!service.installed) return service.available ? 'ready to install' : 'Docker is not available';
  if (!service.owned) return 'ownership check failed';
  if (service.healthy) return 'healthy';
  if (service.running) return 'running, but search is unhealthy';
  return 'stopped';
}

function addManagedSearxngAction(host, action, label, disabled = false) {
  const button = document.createElement('button');
  button.type = 'button';
  button.dataset.searxngAction = action;
  button.textContent = label;
  button.disabled = disabled;
  host.appendChild(button);
}

async function loadManagedSearxng() {
  const statusNode = el('andromeda-searxng-status');
  const meta = el('andromeda-searxng-meta');
  const actions = el('andromeda-searxng-actions');
  if (!statusNode || !meta || !actions) return;
  actions.replaceChildren();
  statusNode.dataset.state = '';
  try {
    const service = await jsonRequest('/api/system/searxng');
    statusNode.textContent = managedSearxngState(service);
    meta.textContent = `${service.bind} · ${service.version} · ${service.license}${service.data_kept ? ' · data kept' : ''}`;
    if (!service.installed) {
      if (service.support_verified) addManagedSearxngAction(actions, 'install', 'install', !service.available);
      return;
    }
    if (!service.owned) return;
    addManagedSearxngAction(actions, service.running ? 'stop' : 'start', service.running ? 'stop' : 'start', !service.available);
    addManagedSearxngAction(actions, 'restart', 'restart', !service.available);
    addManagedSearxngAction(actions, 'test', 'test search', !service.available || !service.running);
    addManagedSearxngAction(actions, 'update', 'safe update', !service.available);
    addManagedSearxngAction(actions, 'rollback', 'rollback', !service.available);
    addManagedSearxngAction(actions, 'uninstall', 'uninstall · keep data');
  } catch (error) {
    statusNode.textContent = error.message || 'local SearXNG status unavailable';
    statusNode.dataset.state = 'error';
    meta.textContent = 'External search providers remain available.';
  }
}

async function manageSearxng(action, button) {
  if (action === 'uninstall'
    && !await confirmDialog('uninstall the Alles-managed SearXNG service? its settings and data will be kept.')) return;
  button.disabled = true;
  const statusNode = el('andromeda-searxng-status');
  if (statusNode) statusNode.textContent = `${action} in progress…`;
  const endpoint = `/api/system/searxng/${action}`;
  let actionMessage = '';
  let actionState = '';
  try {
    const result = await jsonRequest(endpoint, { method: 'POST' });
    if (action === 'test') actionMessage = `search passed · ${result.results || 0} results`;
    await loadSearchConfiguration();
  } catch (error) {
    actionMessage = error.message || `${action} failed`;
    actionState = 'error';
  } finally {
    await loadManagedSearxng();
    await loadProviderChoices();
    if (statusNode && actionMessage) {
      statusNode.textContent = actionMessage;
      statusNode.dataset.state = actionState;
    }
  }
}

function openSettings() {
  const panel = el('andromeda-settings-panel');
  if (!panel) return;
  panel.hidden = false;
  el('andromeda-settings-button')?.setAttribute('aria-expanded', 'true');
  loadSearchConfiguration();
  loadManagedSearxng();
  panel.querySelector('.custom-select, button')?.focus();
}

function closeSettings({ restoreFocus = false } = {}) {
  const panel = el('andromeda-settings-panel');
  if (!panel || panel.hidden) return;
  panel.hidden = true;
  el('andromeda-settings-button')?.setAttribute('aria-expanded', 'false');
  if (restoreFocus) el('andromeda-settings-button')?.focus();
}

export function andromedaLandingUrl(value) {
  const url = new URL(value, 'http://localhost');
  url.searchParams.delete('q');
  return `${url.pathname}${url.search}${url.hash}`;
}

function resetToLanding() {
  _searchAbort?.abort();
  _overviewAbort?.abort();
  void cancelVerification();
  _searchGeneration += 1;
  _state = freshState();
  clearVerificationView();
  setPageState('idle');
  setCategory('all', { search: false });
  if (el('andromeda-query')) el('andromeda-query').value = '';
  window.history.replaceState(
    window.history.state,
    '',
    andromedaLandingUrl(window.location.href),
  );
  closeSettings();
  requestAnimationFrame(() => el('andromeda-query')?.focus());
}

function bindOnce() {
  if (_bound) return;
  _bound = true;
  initCustomDropdowns(el('andromeda-view'));
  el('andromeda-form')?.addEventListener('submit', event => {
    event.preventDefault();
    runAndromedaSearch();
  });
  el('andromeda-query')?.addEventListener('input', event => {
    el('andromeda-form')?.toggleAttribute('data-ready', !!event.currentTarget.value.trim());
  });
  document.querySelectorAll('[data-andromeda-category]').forEach(button => {
    button.addEventListener('click', () => setCategory(button.dataset.andromedaCategory));
  });
  for (const id of ['andromeda-results-toggle', 'andromeda-overview-toggle']) {
    el(id)?.addEventListener('click', () => {
      const next = !pressed(id);
      setPressed(id, next);
      const setting = id === 'andromeda-results-toggle'
        ? 'andromeda_normal_results' : 'andromeda_overview';
      queueSearchConfigurationWrite(
        () => patchSearchSettings({ [setting]: next }),
      ).catch(() => {});
    });
  }
  el('andromeda-verification-toggle')?.addEventListener('click', () => {
    const next = !pressed('andromeda-verification-toggle');
    setPressed('andromeda-verification-toggle', next);
    queueSearchConfigurationWrite(
      () => patchSearchSettings({ andromeda_verification_enabled: next }),
    ).catch(() => {});
  });
  el('andromeda-verifier-mode')?.addEventListener('change', () => {
    queueSearchConfigurationWrite(
      () => patchSearchSettings({
        andromeda_verifier_mode: providerValue('andromeda-verifier-mode', 'freshness-sensitive'),
      }),
    ).catch(() => {});
  });
  for (const id of ['andromeda-primary-provider', 'andromeda-fallback-provider', 'andromeda-result-count']) {
    el(id)?.addEventListener('change', () => saveSearchConfiguration().catch(() => {}));
  }
  el('andromeda-band')?.addEventListener('change', () => {
    const band = providerValue('andromeda-band', 'standard');
    queueSearchConfigurationWrite(
      () => patchSearchSettings({ andromeda_model_band: band }),
    ).catch(() => {});
  });
  for (const id of Object.keys(SEARCH_CREDENTIAL_FIELDS)) {
    el(id)?.addEventListener('blur', event => saveSearchCredential(event.currentTarget));
  }
  document.querySelectorAll('[data-andromeda-clear-setting]').forEach(button => {
    button.addEventListener('pointerdown', () => {
      const input = el(button.dataset.andromedaClearSetting);
      if (input) {
        _credentialClearPending.add(input.id);
        // A cancelled pointer gesture has no click to perform the clear.
        setTimeout(() => {
          if (!button.disabled) _credentialClearPending.delete(input.id);
        }, 0);
      }
    });
    button.addEventListener('click', () => clearSearchCredential(button));
  });
  el('andromeda-searxng-refresh')?.addEventListener('click', loadManagedSearxng);
  el('andromeda-searxng-actions')?.addEventListener('click', event => {
    const button = event.target.closest('[data-searxng-action]');
    if (button) manageSearxng(button.dataset.searxngAction, button);
  });
  el('andromeda-cancel-overview')?.addEventListener('click', () => _overviewAbort?.abort());
  el('andromeda-verification-retry')?.addEventListener('click', () => {
    if (!_state.query || !_state.overview?.status) return;
    void startVerification(
      _state.query,
      _state.overview,
      _state.overviewSeed.length ? _state.overviewSeed : _state.results,
      _searchGeneration,
      { manual: true },
    );
  });
  el('andromeda-verification-details-toggle')?.addEventListener('click', event => {
    const details = el('andromeda-verification-details');
    if (!details) return;
    details.hidden = !details.hidden;
    event.currentTarget.setAttribute('aria-expanded', String(!details.hidden));
    event.currentTarget.textContent = details.hidden ? 'what changed' : 'hide changes';
  });
  el('andromeda-save')?.addEventListener('click', saveCurrent);
  el('andromeda-explain')?.addEventListener('click', explainResults);
  el('andromeda-more-results')?.addEventListener('click', loadMoreResults);
  el('andromeda-home')?.addEventListener('click', resetToLanding);
  for (const id of ['andromeda-go-home', 'andromeda-idle-home']) {
    el(id)?.addEventListener('click', () => window._navigateHome?.());
  }
  el('andromeda-settings-button')?.addEventListener('click', () => settingsOpen() ? closeSettings() : openSettings());
  el('andromeda-idle-settings')?.addEventListener('click', openSettings);
  el('andromeda-settings-close')?.addEventListener('click', () => closeSettings({ restoreFocus: true }));
  el('andromeda-evidence-toggle')?.addEventListener('click', event => {
    const evidence = el('andromeda-evidence');
    if (!evidence) return;
    evidence.hidden = !evidence.hidden;
    event.currentTarget.setAttribute('aria-expanded', String(!evidence.hidden));
    event.currentTarget.textContent = evidence.hidden ? tr('andromeda.show_sources') : tr('andromeda.hide_sources');
  });
  bindRecovery();
  document.addEventListener('click', event => {
    const panel = el('andromeda-settings-panel');
    if (!panel || panel.hidden) return;
    if (panel.contains(event.target) || el('andromeda-settings-button')?.contains(event.target) || el('andromeda-idle-settings')?.contains(event.target)) return;
    if (event.target.closest('.custom-dropdown-panel')) return;
    closeSettings();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && settingsOpen()) {
      event.preventDefault();
      closeSettings({ restoreFocus: true });
    }
  });
  window.addEventListener('alles:localization-change', () => {
    renderAndromedaResults(_state.results, _state.resultStatus, category());
    updateMoreResults();
  });
}

export async function initAndromeda() {
  bindOnce();
  await loadProviderChoices();
  await loadModelChoices();
  try {
    const settings = await loadSearchConfiguration();
    if (settings) {
      setPressed('andromeda-results-toggle', settings.andromeda_normal_results !== false);
      setPressed('andromeda-overview-toggle', settings.andromeda_overview !== false);
      setDropdownValue(el('andromeda-band'), settings.andromeda_model_band || 'standard');
    }
  } catch {}
  await loadManagedSearxng();
  await loadSaved();
  const query = new URLSearchParams(location.search).get('q');
  if (query && !_state.rawQuery) runAndromedaSearch(query);
  else if (!_state.rawQuery) {
    setPageState('idle');
    requestAnimationFrame(() => el('andromeda-query')?.focus());
  }
}

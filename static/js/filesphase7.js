import { toast } from './util.js';
import { prompt as dlgPrompt, confirm as dlgConfirm } from './dialog.js';
import { formatDate } from './i18n.js';
import { replaceRouteUrl } from './route_history.js';

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

const state = {
  locations: [],
  locationId: '',
  cwd: '',
  sort: 'name',
  order: '',
  view: 'all',
  items: [],
  viewItems: [],
  selected: new Map(),
  current: null,
  offline: new Map(),
  operations: [],
  transferAction: 'copy',
  detailReturnPath: '',
  previewPath: '',
  hiddenCompleted: true,
  indexStatus: new Map(),
  searchTerm: '',
  vaultReviewSignature: '',
  vaultReview: null,
};

let initialized = false;
let uploadActive = false;
let selectionRestoreActive = false;
let versionRestoreActive = false;
let operationPoll = 0;
let searchTimer = 0;
let searchSequence = 0;
let viewSequence = 0;
let previewSequence = 0;
let previewReturnFocus = null;
let detailSequence = 0;
let indexPoll = 0;
const indexRevision = new Map();
let filesRetry = null;
const dialogReturnFocus = new Map();
const dialogBackground = new Map();

function icon(name) {
  if (window.icon) return window.icon(name);
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 6h6l2 2h8v10H4z"/></svg>';
}

function locationIcon(kind) {
  if (kind === 'webdav') return icon('cloud');
  if (kind === 's3') return icon('database');
  return icon('folder');
}

function formatSize(value) {
  if (value === null || value === undefined || value === '') return '';
  const size = Number(value);
  if (!Number.isFinite(size) || size < 0) return '';
  if (size < 1024) return `${size} B`;
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 ** 3) return `${(size / 1024 ** 2).toFixed(1)} MB`;
  return `${(size / 1024 ** 3).toFixed(1)} GB`;
}

function formatChanged(value) {
  if (!value) return '';
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000);
  if (seconds < 90) return 'just now';
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  if (seconds < 86400 * 30) return `${Math.round(seconds / 86400)}d ago`;
  return formatDate(date);
}

function basename(path) {
  return String(path || '').split('/').filter(Boolean).pop() || '';
}

function joinPath(...parts) {
  return parts.map(part => String(part || '').replace(/^\/+|\/+$/g, '')).filter(Boolean).join('/');
}

function query(values = {}) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) params.set(key, value);
  });
  const text = params.toString();
  return text ? `?${text}` : '';
}

async function request(url, options = {}, fetcher = fetch) {
  const response = await fetcher(url, options);
  const type = response.headers.get('content-type') || '';
  const data = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = data && typeof data === 'object' ? data.detail : data;
    const message = typeof detail === 'string' ? detail : detail?.message;
    const error = new Error(message || `request failed (${response.status})`);
    error.detail = detail;
    error.status = response.status;
    throw error;
  }
  return data;
}

function jsonOptions(method, body) {
  return {
    method,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  };
}

function currentLocation() {
  return state.locations.find(location => location.id === state.locationId) || null;
}

function isWritable(location = currentLocation()) {
  return Boolean(location && location.enabled && location.access === 'managed');
}

function locationLabel(location) {
  if (!location) return '';
  if (location.kind === 'local') return location.root_path || 'local folder';
  if (location.kind === 's3') return [location.endpoint, location.bucket].filter(Boolean).join(' / ');
  return location.endpoint || 'WebDAV';
}

function writeUrl() {
  try {
    const url = new URL(location.href);
    if (state.locationId) url.searchParams.set('location', state.locationId);
    else url.searchParams.delete('location');
    if (state.cwd) url.searchParams.set('p', state.cwd);
    else url.searchParams.delete('p');
    replaceRouteUrl(url);
  } catch {}
}

async function loadLocations(fetcher = fetch) {
  const data = await request('/api/storage-locations', {}, fetcher);
  state.locations = data.locations || [];
  const requested = new URLSearchParams(location.search).get('location') || '';
  if (!state.locations.some(location => location.id === state.locationId)) {
    state.locationId = state.locations.some(location => location.id === requested)
      ? requested
      : (state.locations.find(location => location.is_default)?.id || state.locations[0]?.id || '');
  }
  renderLocations();
  renderLocationStatus();
  void loadIndexStatus(state.locationId);
}

function renderLocations() {
  const host = $('files-location-list');
  if (!host) return;
  host.hidden = state.locations.length < 2;
  if ($('files-locations-label')) $('files-locations-label').hidden = host.hidden;
  host.innerHTML = state.locations.map(location => `
    <button class="files-location-button${location.id === state.locationId ? ' is-active' : ''}"
      type="button" data-location-id="${esc(location.id)}" aria-pressed="${location.id === state.locationId}">
      ${locationIcon(location.kind)}
      <span class="files-location-copy">
        <strong>${esc(location.name)}</strong>
        <small>${esc(location.kind === 'local' ? 'local' : location.kind.toUpperCase())}</small>
      </span>
      <span class="files-location-access">${location.access === 'managed' ? 'managed' : 'read only'}</span>
    </button>`).join('');
}

function renderAppStatus(location, index) {
  const host = $('files-app-status');
  if (!host) return;
  if (!location) {
    host.textContent = 'no location';
    return;
  }
  if (['queued', 'running'].includes(index.state)) {
    host.textContent = 'indexing';
    return;
  }
  if (index.state === 'error') {
    host.textContent = 'indexing failed';
    return;
  }
  host.textContent = location.access === 'managed' ? '' : 'read only';
}

function renderLocationStatus(message) {
  const host = $('files-location-status');
  const location = currentLocation();
  if (!location) {
    renderAppStatus(null, { state: 'idle' });
    if (host) host.hidden = true;
    if ($('files-settings-btn')) $('files-settings-btn').disabled = true;
    return;
  }
  const index = state.indexStatus.get(location.id) || { state: 'idle', files_indexed: 0 };
  renderAppStatus(location, index);
  if (!host) return;
  host.hidden = false;
  $('files-settings-btn').disabled = false;
  const notice = $('files-location-message');
  if (host.dataset.locationId !== location.id) notice.textContent = '';
  host.dataset.locationId = location.id;
  if (message !== undefined) notice.textContent = message;
  $('files-current-location-name').textContent = location.name;
  $('files-current-location-path').textContent = locationLabel(location);
  const kind = location.kind === 'local' ? 'local folder' : location.kind.toUpperCase();
  $('files-current-location-access').textContent = `${kind} · ${location.access === 'managed' ? 'changes allowed' : 'read only'}`;
  $('files-index-help').textContent = location.kind === 'local'
    ? 'Index readable text for search without changing your files. Local filename search works without an index.'
    : 'Index readable text to search this location. Refresh the index after changing files.';
  const indexing = ['queued', 'running'].includes(index.state);
  const indexCopy = indexing
    ? `indexing${index.files_indexed ? ` · ${index.files_indexed} files` : ''}`
    : index.state === 'completed'
      ? `${index.files_indexed} files indexed`
      : index.state === 'error'
        ? (index.error || 'indexing failed')
        : 'not indexed yet';
  host.querySelector('.files-location-index-state').textContent = indexCopy;
  const indexButton = host.querySelector('[data-location-action="index"]');
  if (indexing && document.activeElement === indexButton) {
    $('files-settings-dialog').querySelector('[data-files-dialog-close]').focus();
  }
  indexButton.disabled = indexing;
  indexButton.textContent = index.state === 'completed' ? 'refresh search index' : 'index for search';
  const access = host.querySelector('[data-location-action="access"]');
  access.hidden = location.is_default;
  access.textContent = location.access === 'managed' ? 'make read only' : 'allow changes';
  host.querySelector('[data-location-action="remove"]').hidden = location.is_default;
}

async function loadIndexStatus(requestedLocationId = state.locationId, fetcher = fetch) {
  const locationId = requestedLocationId;
  if (!locationId) return;
  const revision = indexRevision.get(locationId) || 0;
  try {
    const status = await request(
      `/api/storage-locations/${encodeURIComponent(locationId)}/index`,
      {},
      fetcher,
    );
    if (locationId !== state.locationId || revision !== (indexRevision.get(locationId) || 0)) return;
    // An idle server has not resolved a failed start; keep the error until retry or progress.
    if (state.indexStatus.get(locationId)?.state === 'error' && status.state === 'idle') return;
    state.indexStatus.set(locationId, status);
    renderLocationStatus();
    if (['queued', 'running'].includes(status.state)) scheduleIndexPoll(locationId);
  } catch {
    if (locationId !== state.locationId || revision !== (indexRevision.get(locationId) || 0)) return;
    const known = state.indexStatus.get(locationId);
    if (['queued', 'running'].includes(known?.state)) scheduleIndexPoll(locationId, 1500);
  }
}

function scheduleIndexPoll(locationId = state.locationId, delay = 750) {
  clearTimeout(indexPoll);
  indexPoll = setTimeout(() => loadIndexStatus(locationId), delay);
}

async function startIndexing() {
  const locationId = state.locationId;
  if (!locationId) return;
  let revision = (indexRevision.get(locationId) || 0) + 1;
  indexRevision.set(locationId, revision);
  state.indexStatus.set(locationId, {
    ...(state.indexStatus.get(locationId) || {}),
    location_id: locationId,
    state: 'queued',
    error: '',
  });
  renderLocationStatus();
  scheduleIndexPoll(locationId);
  try {
    const status = await request(
      `/api/storage-locations/${encodeURIComponent(locationId)}/index`,
      { method: 'POST' },
    );
    if (locationId !== state.locationId || revision !== (indexRevision.get(locationId) || 0)) return;
    revision += 1;
    indexRevision.set(locationId, revision);
    state.indexStatus.set(locationId, status);
    renderLocationStatus();
    scheduleIndexPoll(locationId);
  } catch (error) {
    if (locationId !== state.locationId || revision !== (indexRevision.get(locationId) || 0)) return;
    revision += 1;
    indexRevision.set(locationId, revision);
    state.indexStatus.set(locationId, {
      ...(state.indexStatus.get(locationId) || {}),
      state: 'error',
      error: error.message,
    });
    renderLocationStatus();
  }
}

function applyWriteState() {
  const writable = isWritable();
  const trashView = state.view === 'trash';
  const cacheView = state.view === 'offline';
  for (const id of ['files-mkdir-btn', 'files-upload-btn']) {
    const button = $(id);
    if (!button) continue;
    button.hidden = trashView || cacheView;
    button.disabled = !writable || trashView || cacheView;
    button.title = trashView
      ? 'not available in recently deleted'
      : cacheView
        ? 'offline copies are read only'
        : (writable ? '' : 'this location is read only');
  }
  document.querySelectorAll('[data-files-bulk]').forEach(button => {
    const action = button.dataset.filesBulk;
    const cacheOnlyDescendant = cacheView
      && [...state.selected.values()].some(item => item.cache_only
        && !state.offline.has(item.path || item.normalized_path));
    button.hidden = (trashView && !['restore', 'clear'].includes(action))
      || (cacheView && !['offline', 'clear'].includes(action))
      || (action === 'restore' && (!trashView || state.selected.size !== 1));
    if (action === 'restore') {
      button.disabled = !writable || state.selected.size !== 1;
      button.setAttribute('aria-busy', String(selectionRestoreActive));
      button.setAttribute('aria-disabled', String(button.disabled || selectionRestoreActive));
    }
    if (['move', 'delete'].includes(action)) button.disabled = !writable || cacheView;
    if (action === 'offline') button.disabled = cacheOnlyDescendant;
  });
}

function renderFilesLoading(host) {
  filesRetry = null;
  host.setAttribute('aria-busy', 'true');
  host.innerHTML = `<div class="files-loading files-loading-list" role="status">
    <span class="sr-only">loading files</span>
    ${Array.from({ length: 5 }, () => `<div class="files-loading-row" aria-hidden="true">
      <span class="files-loading-block"></span><span class="files-loading-block"></span>
      <span class="files-loading-block"></span><span class="files-loading-block"></span>
    </div>`).join('')}
  </div>`;
}

function renderFilesError(host, error, retry = null) {
  filesRetry = typeof retry === 'function' ? retry : null;
  host.setAttribute('aria-busy', 'false');
  host.innerHTML = `<div class="files-error" role="alert">
    <span>${esc(error.message)}</span>
    <button class="files-text-button" type="button" data-files-retry>retry</button>
  </div>`;
}

function beginFilesRequest(host) {
  state.selected.clear();
  renderSelection();
  closeDetails();
  renderFilesLoading(host);
}

export async function loadFiles(path = state.cwd, fetcher = fetch) {
  const host = $('files-list');
  if (!host) return;
  clearFilesSearch();
  const sequence = ++viewSequence;
  showNotice('');
  state.view = 'all';
  syncViewButtons();
  beginFilesRequest(host);
  try {
    if (!state.locations.length) await loadLocations(fetcher);
    if (!state.locationId) throw new Error('no storage location is available');
    const locationId = state.locationId;
    const data = await request(
      '/api/files/list' + query({
        path,
        location_id: locationId,
        sort: state.sort,
        order: state.order,
      }),
      {},
      fetcher,
    );
    if (sequence !== viewSequence || locationId !== state.locationId) return;
    state.cwd = data.path || '';
    state.items = data.items || [];
    state.viewItems = [...state.items];
    const offline = await loadOfflineState(locationId, fetcher);
    if (sequence !== viewSequence || locationId !== state.locationId) return;
    state.offline = offline;
    renderBreadcrumb();
    renderItems();
    renderSelection();
    applyWriteState();
    writeUrl();
  } catch (error) {
    if (sequence !== viewSequence) return;
    state.items = [];
    renderFilesError(host, error, () => loadFiles(path));
    showNotice(error.message, true);
  }
}

async function loadCurrentView() {
  if (state.view === 'all') return loadFiles(state.cwd);
  const host = $('files-list');
  if (!host) return;
  searchSequence += 1;
  const sequence = ++viewSequence;
  const locationId = state.locationId;
  const view = state.view;
  showNotice('');
  state.viewItems = [];
  beginFilesRequest(host);
  try {
    if (view === 'starred') {
      const data = await request('/api/files/starred' + query({ location_id: locationId }));
      if (sequence !== viewSequence || locationId !== state.locationId) return;
      state.items = (data.items || []).map(item => ({
        ...item,
        name: basename(item.path),
        type: item.type || 'file',
        starred: true,
      }));
    } else if (view === 'offline') {
      const data = state.cwd
        ? await request('/api/files/offline/list' + query({
          location_id: locationId,
          path: state.cwd,
        }))
        : await request('/api/files/offline' + query({ location_id: locationId }));
      if (sequence !== viewSequence || locationId !== state.locationId) return;
      state.cwd = data.path || state.cwd || '';
      state.items = (data.items || []).map(item => ({
        ...item,
        path: item.path || item.normalized_path,
        name: item.name || basename(item.path || item.normalized_path),
        type: item.type || 'file',
        offline_state: item.offline_state || item.state || 'ready',
        cache_only: true,
      }));
      const explicitOffline = state.cwd
        ? await loadOfflineState(locationId)
        : new Map((data.items || []).map(item => [item.normalized_path || item.path, item]));
      if (sequence !== viewSequence || locationId !== state.locationId) return;
      state.offline = explicitOffline;
    } else if (view === 'trash') {
      const data = await request('/api/files/trash' + query({ location_id: locationId }));
      if (sequence !== viewSequence || locationId !== state.locationId) return;
      state.items = (data || []).map(item => ({
        ...item,
        path: item.ref,
        row_key: `trash:${item.id}`,
        name: item.name || basename(item.ref),
        type: item.type || 'file',
        trash_id: item.id,
        mtime: item.trashed_at,
      }));
    }
    state.viewItems = [...state.items];
    if ((view === 'offline' || view === 'starred') && state.searchTerm) {
      filterCurrentItems(state.searchTerm);
    }
    renderBreadcrumb();
    renderItems();
    renderSelection();
  } catch (error) {
    if (sequence !== viewSequence || locationId !== state.locationId) return;
    state.items = [];
    state.viewItems = [];
    renderFilesError(host, error, () => loadCurrentView());
  }
}

async function refreshAfterOperation(searchTerm = state.searchTerm) {
  if (['starred', 'offline'].includes(state.view) && searchTerm) {
    return loadCurrentView();
  }
  return searchTerm ? searchFiles(searchTerm) : loadCurrentView();
}

function syncViewButtons() {
  document.querySelectorAll('[data-files-view]').forEach(button => {
    const active = button.dataset.filesView === state.view;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-current', active ? 'page' : 'false');
  });
}

function renderBreadcrumb() {
  const host = $('files-breadcrumb');
  const location = currentLocation();
  if (!host || !location) return;
  if (state.view === 'offline') {
    const segments = [
      `<button class="crumb" type="button" data-crumb-path="">${esc(location.name)}</button>`,
      '<span class="crumb-sep">/</span>',
      '<button class="crumb" type="button" data-crumb-path="">offline</button>',
    ];
    let path = '';
    state.cwd.split('/').filter(Boolean).forEach(part => {
      path = joinPath(path, part);
      segments.push('<span class="crumb-sep">/</span>');
      segments.push(`<button class="crumb" type="button" data-crumb-path="${esc(path)}">${esc(part)}</button>`);
    });
    host.innerHTML = segments.join('');
    return;
  }
  if (state.view !== 'all') {
    host.innerHTML = `<button class="crumb" type="button" data-crumb-path="">${esc(location.name)}</button><span class="crumb-sep">/</span><span class="crumb">${esc(state.view === 'trash' ? 'recently deleted' : state.view)}</span>`;
    return;
  }
  const parts = state.cwd.split('/').filter(Boolean);
  const segments = [`<button class="crumb" type="button" data-crumb-path="">${esc(location.name)}</button>`];
  let path = '';
  parts.forEach(part => {
    path = joinPath(path, part);
    segments.push('<span class="crumb-sep">/</span>');
    segments.push(`<button class="crumb" type="button" data-crumb-path="${esc(path)}">${esc(part)}</button>`);
  });
  host.innerHTML = segments.join('');
}

function itemIcon(item) {
  if (item.type === 'dir') return icon('folder');
  if (/\.(png|jpe?g|gif|webp|svg|bmp|heic|avif)$/i.test(item.name || item.path)) return icon('image');
  return icon('file');
}

function canSendToPhotos(item) {
  if (item.type === 'dir') return true;
  return /\.(?:jpe?g|png|webp|gif|bmp|tiff?|heic|heif|dng|cr2|cr3|nef|arw|raf|rw2|orf|pef|mp4|mov|m4v|webm)$/i
    .test(item.name || item.path || '');
}

function itemKey(item) {
  return item?.row_key || item?.path || item?.normalized_path || '';
}

function renderItems() {
  const host = $('files-list');
  if (!host) return;
  host.setAttribute('aria-busy', 'false');
  if (!state.items.length) {
    const copy = state.view === 'all' ? 'this folder is empty' : `no ${state.view === 'trash' ? 'deleted files' : state.view + ' files'}`;
    host.innerHTML = `<div class="files-empty">${esc(copy)}</div>`;
    updateSelectAll();
    return;
  }
  host.innerHTML = state.items.map(item => {
    const path = item.path || item.normalized_path || '';
    const key = itemKey(item);
    const selected = state.selected.has(key);
    const current = itemKey(state.current) === key;
    const stateCopy = item.offline_state && item.offline_state !== 'ready' ? item.offline_state : '';
    return `
      <div class="file-row${current ? ' is-current' : ''}" tabindex="0" data-path="${esc(key)}" data-type="${esc(item.type || 'file')}"${item.trash_id ? ` data-trash-id="${esc(item.trash_id)}"` : ''}>
        <button class="files-check" type="button" role="checkbox" aria-checked="${selected}" aria-label="select ${esc(item.name || basename(path))}" data-file-select></button>
        <span class="file-main">${itemIcon(item)}<button class="file-name-button" type="button" data-file-open>${esc(item.name || basename(path))}${stateCopy ? ` · ${esc(stateCopy)}` : ''}</button></span>
        <span class="file-size">${esc(formatSize(item.size))}</span>
        <span class="file-changed">${esc(formatChanged(item.mtime || item.updated_at))}</span>
      </div>`;
  }).join('');
  updateSelectAll();
}

function findItem(key) {
  return state.items.find(item => itemKey(item) === key) || null;
}

function toggleSelection(path, force) {
  const item = findItem(path);
  if (!item) return;
  const selected = force === undefined ? !state.selected.has(path) : Boolean(force);
  if (selected) state.selected.set(path, item);
  else state.selected.delete(path);
  const check = document.querySelector(`.file-row[data-path="${CSS.escape(path)}"] [data-file-select]`);
  check?.setAttribute('aria-checked', String(selected));
  renderSelection();
  updateSelectAll();
}

function updateSelectAll() {
  const button = $('files-select-all');
  if (!button) return;
  const count = state.selected.size;
  button.setAttribute('aria-checked', count && count < state.items.length ? 'mixed' : String(Boolean(count && count === state.items.length)));
}

function renderSelection() {
  const bar = $('files-selection-bar');
  if (!bar) return;
  const count = state.selected.size;
  bar.hidden = count === 0;
  $('files-selection-count').textContent = `${count} selected`;
  applyWriteState();
  revealFileControl(document.activeElement);
}

function selectAll() {
  const allSelected = state.items.length && state.selected.size === state.items.length;
  state.selected.clear();
  if (!allSelected) state.items.forEach(item => state.selected.set(itemKey(item), item));
  renderItems();
  renderSelection();
}

function openItem(item) {
  if (!item) return;
  if (state.view === 'trash') {
    renderDetails(item);
    return;
  }
  if (item.type === 'dir') {
    if (state.view === 'offline') {
      state.cwd = item.path || item.normalized_path || '';
      loadCurrentView();
      return;
    }
    loadFiles(item.path);
    return;
  }
  renderDetails(item);
}

async function renderDetails(item) {
  const path = item.path || item.normalized_path;
  const key = itemKey(item);
  const locationId = state.locationId;
  const detailRequest = ++detailSequence;
  state.detailReturnPath = key;
  state.current = item;
  renderItems();
  const panel = $('files-detail-panel');
  const host = $('files-detail-content');
  if (!panel || !host) return;
  const importKey = `${locationId}:${key}`;
  if (panel.dataset.photoImportKey !== importKey) {
    const feedback = $('files-photo-import-feedback');
    if (feedback) {
      feedback.replaceChildren();
      feedback.hidden = true;
    }
    panel.dataset.photoImportKey = importKey;
  }
  panel.hidden = false;
  const offline = state.offline.get(path);
  const offlineState = item.offline_state || item.state || offline?.state || '';
  const cacheReady = Boolean(item.cache_only && (!offlineState || offlineState === 'ready'));
  const writable = isWritable();
  const raw = cacheReady
    ? `/api/files/offline/raw${query({ path, location_id: locationId })}`
    : `/api/files/raw${query({ path, location_id: locationId })}`;
  const readable = state.view !== 'offline' || cacheReady;
  host.innerHTML = `
    <h2 class="files-detail-name">${esc(item.name || basename(path))}</h2>
    <div class="files-detail-path">${esc(path)}</div>
    <div class="files-detail-actions">
      ${state.view === 'trash'
        ? (writable ? '<button class="files-text-button" type="button" data-detail-action="restore">restore</button>' : '')
        : `${readable ? '<button class="files-text-button" type="button" data-detail-action="open">open</button>' : ''}
           ${readable && item.type !== 'dir' ? `<a class="files-text-button" href="${esc(raw)}&download=1" download>download</a>` : ''}
           ${offline
             ? '<button class="files-text-button" type="button" data-detail-action="offline-refresh">refresh offline copy</button><button class="files-text-button" type="button" data-detail-action="offline-remove">remove offline copy</button>'
             : state.view !== 'offline' ? '<button class="files-text-button" type="button" data-detail-action="offline">keep offline</button>' : ''}
           ${state.view === 'offline' ? '' : `<button class="files-text-button" type="button" data-detail-action="star">${item.starred ? 'unstar' : 'star'}</button>`}
           ${state.view !== 'offline' && writable ? '<button class="files-text-button" type="button" data-detail-action="rename">rename</button>' : ''}
           ${state.view !== 'offline' && writable ? '<button class="files-text-button files-danger" type="button" data-detail-action="delete">delete</button>' : ''}
           ${state.view !== 'offline' && canSendToPhotos(item) ? '<button class="files-text-button" type="button" data-detail-action="photos">send to Photos</button>' : ''}`}
    </div>
    <dl class="files-detail-meta">
      <dt>location</dt><dd>${esc(currentLocation()?.name || '')}</dd>
      <dt>access</dt><dd>${isWritable() ? 'managed' : 'read only'}</dd>
      <dt>kind</dt><dd>${esc(item.type || 'file')}</dd>
      <dt>size</dt><dd data-files-detail-size>${esc(formatSize(item.size) || 'unknown')}</dd>
      <dt>offline</dt><dd>${esc(offlineState || 'online only')}</dd>
    </dl>
    <div id="files-detail-versions"></div>`;
  $('files-detail-close')?.focus();
  if (state.view !== 'trash' && !cacheReady && item.type !== 'dir') {
    loadVersions(path, locationId, detailRequest);
  }
}

async function loadVersions(path, locationId, detailRequest) {
  const item = state.current;
  const panel = $('files-detail-panel');
  const host = $('files-detail-versions');
  if (!host || !panel) return;
  const current = () => detailRequest === detailSequence && locationId === state.locationId
    && state.current === item && !panel.hidden;
  try {
    const versions = await request('/api/files/versions' + query({ path, location_id: locationId }));
    if (!current()) return;
    const expanded = host.querySelector('details')?.open;
    host.innerHTML = versions.length ? `<details class="files-version-history" ${expanded ? 'open' : ''}>
      <summary>version history (${versions.length})</summary>
      <ul>${versions.map((version, index) => `<li>
        <span>version ${versions.length - index} · ${esc(formatDate(version.created_at))} · ${esc(formatSize(version.size))}</span>
        ${isWritable() ? `<button type="button" class="files-text-button" data-version-id="${esc(version.id)}" aria-label="restore version ${versions.length - index}">restore</button>` : ''}
      </li>`).join('')}</ul>
    </details><p class="files-version-feedback" role="status" tabindex="-1"></p>` : '';
    host.querySelectorAll('[data-version-id]').forEach(button => button.addEventListener('click', async () => {
      if (versionRestoreActive || !current()) return;
      versionRestoreActive = true;
      host.querySelectorAll('button').forEach(control => { control.disabled = true; });
      const feedback = host.querySelector('.files-version-feedback');
      feedback.textContent = 'checking version…';
      let expected = item.etag || '';
      let canceled = false;
      try {
        if (!await dlgConfirm('restore this version? the current file will be kept in version history.') || !current()) {
          canceled = true;
          if (current()) feedback.textContent = 'restore canceled. the current file is unchanged.';
          return;
        }
        while (current()) {
          try {
            const restored = await request('/api/files/versions/restore', jsonOptions('POST', {
              path, id: button.dataset.versionId, location_id: locationId, expected_etag: expected,
            }));
            if (current()) {
              item.etag = restored.etag || '';
              item.size = restored.size ?? versions.find(version => version.id === button.dataset.versionId)?.size ?? item.size;
              const size = $('files-detail-content')?.querySelector('[data-files-detail-size]');
              if (size) size.textContent = formatSize(item.size);
              renderItems();
            }
            await loadVersions(path, locationId, detailRequest);
            if (current()) {
              const result = host.querySelector('.files-version-feedback');
              result.textContent = 'version restored. the previous file remains in version history.';
              result.focus();
            }
            return;
          } catch (error) {
            if (error.detail?.code !== 'file_conflict' || !error.detail.can_replace) throw error;
            const accepted = await dlgConfirm(`${error.message}. Restore this version? The current file will be kept in version history.`);
            if (!accepted || !current()) {
              canceled = true;
              if (current()) feedback.textContent = 'restore canceled. the current file is unchanged.';
              return;
            }
            expected = error.detail.expected_etag;
          }
        }
      } catch (error) {
        if (current()) {
          feedback.textContent = error.message;
          feedback.setAttribute('role', 'alert');
          feedback.focus();
        }
      } finally {
        versionRestoreActive = false;
        if (current()) {
          host.querySelectorAll('button').forEach(control => { control.disabled = false; });
          if (canceled && button.isConnected) button.focus();
        }
      }
    }));
  } catch (error) {
    if (!current()) return;
    host.innerHTML = `<p class="files-version-feedback" role="alert">version history unavailable: ${esc(error.message)}</p>
      <button type="button" class="files-text-button">retry version history</button>`;
    host.querySelector('button').addEventListener('click', () => loadVersions(path, locationId, detailRequest));
  }
}

function closeDetails() {
  detailSequence += 1;
  const returnPath = state.detailReturnPath;
  const panel = $('files-detail-panel');
  const wasOpen = Boolean(panel && !panel.hidden);
  state.current = null;
  if (panel) {
    panel.hidden = true;
    delete panel.dataset.photoImportKey;
  }
  const feedback = $('files-photo-import-feedback');
  if (feedback) {
    feedback.replaceChildren();
    feedback.hidden = true;
  }
  renderItems();
  state.detailReturnPath = '';
  if (!wasOpen || !returnPath) return;
  document.querySelector(`.file-row[data-path="${CSS.escape(returnPath)}"]`)?.focus();
}

async function openPreview(item) {
  if (!item || item.type === 'dir') return;
  const path = item.path || item.normalized_path;
  const sequence = ++previewSequence;
  state.previewPath = path;
  const name = item.name || basename(path);
  const location = state.locationId;
  const offlineState = item.offline_state || item.state || state.offline.get(path)?.state || '';
  const cacheReady = Boolean(item.cache_only && (!offlineState || offlineState === 'ready'));
  if (state.view === 'offline' && !cacheReady) {
    toast('offline copy is not ready', 'error');
    return;
  }
  const raw = cacheReady
    ? `/api/files/offline/raw${query({ path, location_id: location })}`
    : `/api/files/raw${query({ path, location_id: location })}`;
  const modal = $('files-preview-modal');
  const body = $('files-preview-body');
  if (!modal || !body) return;
  $('files-preview-name').textContent = name;
  $('files-preview-dl').href = `${raw}&download=1`;
  previewReturnFocus = document.activeElement;
  modal.style.display = 'flex';
  $('files-preview-close')?.focus();
  if (/\.(png|jpe?g|gif|webp|svg|bmp|heic|avif)$/i.test(name)) {
    body.innerHTML = `<img class="files-preview-img" src="${esc(raw)}" alt="">`;
    return;
  }
  if (/\.pdf$/i.test(name)) {
    body.innerHTML = `<iframe class="files-preview-frame" src="${esc(raw)}#view=FitH" title="${esc(name)}"></iframe>`;
    return;
  }
  if (/\.(mp4|webm|ogv|mov|m4v)$/i.test(name)) {
    body.innerHTML = `<video class="files-preview-media" src="${esc(raw)}" controls playsinline></video>`;
    return;
  }
  if (/\.(mp3|wav|ogg|m4a|flac|aac)$/i.test(name)) {
    body.innerHTML = `<audio class="files-preview-media" src="${esc(raw)}" controls></audio>`;
    return;
  }
  body.innerHTML = '<div class="files-loading">loading preview</div>';
  try {
    const readEndpoint = cacheReady ? '/api/files/offline/read' : '/api/files/read';
    const data = await request(readEndpoint + query({ path, location_id: location }));
    if (sequence !== previewSequence || path !== state.previewPath) return;
    body.innerHTML = data.is_text
      ? `<pre class="files-preview-pre">${esc(data.content)}</pre>`
      : '<div class="files-empty">download this file to open it</div>';
  } catch (error) {
    if (sequence !== previewSequence || path !== state.previewPath) return;
    body.innerHTML = `<div class="files-error">${esc(error.message)}</div>`;
  }
}

function closePreview() {
  previewSequence += 1;
  state.previewPath = '';
  const modal = $('files-preview-modal');
  const body = $('files-preview-body');
  body?.querySelectorAll('audio, video').forEach(media => {
    media.pause();
    media.removeAttribute('src');
  });
  if (body) body.replaceChildren();
  if (modal) modal.style.display = 'none';
  previewReturnFocus?.focus?.();
  previewReturnFocus = null;
}

async function loadOfflineState(locationId = state.locationId, fetcher = fetch) {
  try {
    const data = await request(
      '/api/files/offline' + query({ location_id: locationId }),
      {},
      fetcher,
    );
    return new Map((data.items || []).map(item => [item.normalized_path, item]));
  } catch {
    return new Map();
  }
}

async function toggleOffline(item) {
  const path = item.path || item.normalized_path;
  return setOffline(item, state.offline.has(path) ? 'remove' : 'keep');
}

async function setOffline(item, action = 'keep', refreshView = true) {
  const path = item.path || item.normalized_path;
  const locationId = state.locationId;
  const current = state.offline.get(path);
  if (item.cache_only && !current) {
    toast('remove the parent offline copy instead', 'error');
    return;
  }
  try {
    if (action === 'remove') {
      await request('/api/files/offline', jsonOptions('DELETE', { location_id: locationId, path }));
      if (locationId !== state.locationId) return;
      state.offline.delete(path);
    } else {
      const row = await request('/api/files/offline', jsonOptions('POST', { location_id: locationId, path }));
      if (locationId !== state.locationId) return;
      state.offline.set(path, row);
    }
    const panel = $('files-detail-panel');
    if (state.current === item && panel && !panel.hidden) renderDetails(item);
    if (refreshView && state.view === 'offline') await loadCurrentView();
    return true;
  } catch (error) {
    toast(error.message, 'error');
    return false;
  }
}

async function keepItemsOffline(items) {
  const button = document.querySelector('[data-files-bulk="offline"]');
  if (button) button.disabled = true;
  try {
    for (const item of items) {
      await setOffline(item, 'keep', false);
    }
    if (state.view === 'offline') await loadCurrentView();
  } finally {
    if (button) button.disabled = false;
  }
}

async function setStar(item) {
  const path = item.path || item.normalized_path;
  const locationId = state.locationId;
  const view = state.view;
  try {
    const result = await request('/api/files/star' + query({ path, location_id: locationId }), jsonOptions('PUT', { starred: !item.starred }));
    if (locationId !== state.locationId) return;
    item.starred = result.starred;
    const panel = $('files-detail-panel');
    if (state.current === item && panel && !panel.hidden) renderDetails(item);
    if (state.view === view && view === 'starred' && !item.starred) loadCurrentView();
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function renameItem(item) {
  if (!isWritable()) return;
  const path = item.path || item.normalized_path;
  const oldName = basename(path);
  const name = await dlgPrompt('rename to:', oldName);
  if (!name || name === oldName) return;
  const parent = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
  try {
    await queueOperation({
      action: 'rename',
      source_location_id: state.locationId,
      source_path: path,
      destination_location_id: state.locationId,
      destination_path: joinPath(parent, name),
    });
    closeDetails();
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function deleteItems(items) {
  if (!isWritable() || !items.length) return;
  const locationId = state.locationId;
  const subject = items.length === 1 ? `“${items[0].path || items[0].normalized_path || items[0].name}”` : `${items.length} items`;
  const ok = await dlgConfirm(`move ${subject} to recently deleted? you can restore ${items.length === 1 ? 'it' : 'them'} there.`, { confirmLabel: 'move to recently deleted' });
  if (!ok) return;
  const queued = [];
  try {
    for (const item of items) {
      await queueOperation({
        action: 'delete',
        source_location_id: locationId,
        source_path: item.path || item.normalized_path,
      });
      queued.push(item.path || item.normalized_path);
    }
  } catch (error) {
    queued.forEach(path => state.selected.delete(path));
    renderSelection();
    renderItems();
    toast(error.message, 'error');
    return;
  }
  if (state.locationId === locationId) {
    state.selected.clear();
    renderSelection();
    renderItems();
    closeDetails();
  }
}

async function restoreItem(item, { close = true } = {}) {
  if (!isWritable()) return;
  try {
    const operation = await queueOperation({
      action: 'restore',
      source_location_id: state.locationId,
      source_path: item.trash_id,
    });
    if (close) closeDetails();
    return operation;
  } catch (error) {
    toast(error.message, 'error');
  }
}

function photosImportMessage(result) {
  const imported = Number(result.imported || 0);
  const skipped = Number(result.skipped || 0);
  const ignored = Number(result.ignored || 0);
  const failed = Array.isArray(result.failed) ? result.failed.length : Number(result.failed || 0);
  const parts = [];
  if (imported) parts.push(`${imported} item${imported === 1 ? '' : 's'} sent to Photos`);
  if (skipped) parts.push(`${skipped} already there`);
  if (ignored) parts.push(`${ignored} unsupported file${ignored === 1 ? '' : 's'} skipped`);
  if (failed) parts.push(`${failed} failed`);
  return parts.join(' · ') || 'nothing sent to Photos';
}

async function sendToPhotos(item) {
  const panel = $('files-detail-panel');
  const feedback = $('files-photo-import-feedback');
  const button = panel?.querySelector('[data-detail-action="photos"]');
  const locationId = state.locationId;
  const path = item.path || item.normalized_path;
  const importKey = `${locationId}:${itemKey(item)}`;
  if (!button || !feedback || panel.dataset.photoImportKey !== importKey || button.disabled) return;
  button.disabled = true;
  feedback.hidden = false;
  feedback.textContent = 'sending to Photos…';
  try {
    const result = await request('/api/files/to-photos', jsonOptions('POST', {
      location_id: locationId,
      path,
    }));
    const summary = photosImportMessage(result);
    if (panel.dataset.photoImportKey === importKey && !panel.hidden) {
      const heading = document.createElement('p');
      heading.textContent = summary;
      feedback.replaceChildren(heading);
      if (result.failed?.length) {
        const list = document.createElement('ul');
        for (const failure of result.failed) {
          const entry = document.createElement('li');
          entry.textContent = `${failure.path}: ${failure.error}`;
          list.append(entry);
        }
        feedback.append(list);
      }
    }
    toast(summary, result.failed?.length ? 'error' : 'success');
  } catch (error) {
    if (panel.dataset.photoImportKey === importKey && !panel.hidden) feedback.textContent = error.message;
    toast(error.message, 'error');
  } finally {
    if (panel.dataset.photoImportKey === importKey && !panel.hidden) {
      panel.querySelector('[data-detail-action="photos"]')?.removeAttribute('disabled');
    }
  }
}

function openTransferDialog(action) {
  if (!state.selected.size) return;
  state.transferAction = action;
  const dialog = $('files-transfer-dialog');
  const title = $('files-transfer-dialog-title');
  if (!dialog || !title) return;
  title.textContent = `${action} selected`;
  const destinations = state.locations.filter(location => location.enabled && location.access === 'managed');
  $('files-transfer-locations').innerHTML = destinations.map(location => `
    <button type="button" role="radio" aria-checked="false" data-value="${esc(location.id)}">${esc(location.name)}</button>`).join('');
  $('files-transfer-path').value = '';
  $('files-transfer-error').textContent = '';
  openFilesDialog('transfer', '[role="radio"]');
}

async function submitTransfer() {
  const locationId = $('files-transfer-locations').querySelector('[role="radio"][aria-checked="true"]')?.dataset.value;
  const folder = $('files-transfer-path').value.trim();
  if (!locationId) {
    $('files-transfer-error').textContent = 'choose a destination';
    return;
  }
  const items = [...state.selected.values()];
  const sourceLocationId = state.locationId;
  const action = state.transferAction;
  const queued = [];
  try {
    for (const item of items) {
      const source = item.path || item.normalized_path;
      await queueOperation({
        action: action,
        source_location_id: sourceLocationId,
        source_path: source,
        destination_location_id: locationId,
        destination_path: joinPath(folder, basename(source)),
      });
      queued.push(source);
    }
  } catch (error) {
    queued.forEach(path => state.selected.delete(path));
    renderSelection();
    renderItems();
    $('files-transfer-error').textContent = queued.length
      ? `${queued.length} queued; ${error.message}`
      : error.message;
    return;
  }
  closeDialog('transfer');
  state.selected.clear();
  renderSelection();
  renderItems();
}

async function queueOperation(payload) {
  const refreshContext = {
    locationId: state.locationId,
    cwd: state.cwd,
    view: state.view,
    searchTerm: state.searchTerm,
  };
  const operation = await request('/api/files/operations', jsonOptions('POST', { ...payload, run_now: false }));
  state.operations.unshift(operation);
  renderOperations();
  request(`/api/files/operations/${encodeURIComponent(operation.id)}/run`, { method: 'POST' })
    .then(async () => {
      await loadOperations();
      await refreshQueuedOperation(payload, refreshContext);
    })
    .catch(async error => {
      toast(error.message, 'error');
      await loadOperations();
      await refreshQueuedOperation(payload, refreshContext);
    });
  return operation;
}

async function refreshQueuedOperation(payload, refreshContext) {
  const sameView = state.locationId === refreshContext.locationId
    && state.cwd === refreshContext.cwd
    && state.view === refreshContext.view
    && state.searchTerm === refreshContext.searchTerm;
  const affectsCurrentLocation = [
    payload.source_location_id,
    payload.destination_location_id,
  ].includes(state.locationId);
  const currentViewAffected = affectsCurrentLocation
    && (state.view !== 'trash' || ['delete', 'restore'].includes(payload.action));
  if (sameView || currentViewAffected) {
    const currentPath = state.current?.path || state.current?.normalized_path || '';
    const refreshTerm = sameView ? refreshContext.searchTerm : state.searchTerm;
    await refreshAfterOperation(refreshTerm);
    if (currentPath) {
      const refreshed = findItem(currentPath);
      if (refreshed) await renderDetails(refreshed);
      else closeDetails();
    }
  }
}

async function loadOperations(fetcher = fetch) {
  try {
    const data = await request('/api/files/operations?limit=40', {}, fetcher);
    state.operations = data.operations || [];
    renderOperations();
  } catch {}
}

function pollOperations() {
  const view = $('files-view');
  if (document.visibilityState === 'hidden' || !view || view.style.display === 'none') return;
  loadOperations();
}

function updateOperationClearance() {
  const view = $('files-view');
  const dock = $('files-operation-dock');
  if (!view || !dock) return;
  const dockStyle = getComputedStyle(dock);
  const floating = ['absolute', 'fixed'].includes(dockStyle.position);
  const clearance = dock.hidden || !floating ? 0 : Math.ceil(dock.getBoundingClientRect().height
    + (parseFloat(dockStyle.bottom) || 0) + 8);
  view.style.setProperty('--files-operation-clearance', `${clearance}px`);
  const header = $('files-app-header');
  const headerClearance = header && getComputedStyle(header).position === 'sticky'
    ? header.getBoundingClientRect().height : 0;
  view.style.setProperty('--files-header-clearance', `${headerClearance}px`);
}

function renderOperations() {
  const dock = $('files-operation-dock');
  const host = $('files-operation-list');
  if (!dock || !host) return;
  const history = state.operations.filter(operation => ['completed', 'undone'].includes(operation.state));
  const active = state.operations.filter(operation => !history.includes(operation));
  const toggle = $('files-operations-clear');
  if (toggle) {
    toggle.hidden = history.length === 0;
    toggle.textContent = `${state.hiddenCompleted ? 'show' : 'hide'} history (${history.length})`;
    toggle.setAttribute('aria-expanded', String(!state.hiddenCompleted));
  }
  dock.hidden = state.operations.length === 0;
  const focused = host.contains(document.activeElement) ? document.activeElement : null;
  const focusedId = focused?.closest('[data-operation-id]')?.dataset.operationId;
  const focusedAction = focused?.dataset.operationAction;
  const renderRow = operation => {
    const name = operation.action === 'restore' ? (operation.destination_path || 'file') : operation.source_path;
    const progress = operation.bytes_total
      ? `${Math.min(100, Math.round((operation.bytes_done / operation.bytes_total) * 100))}%`
      : operation.state;
    return `
      <div class="files-operation-row" data-operation-id="${esc(operation.id)}">
        <span class="files-operation-copy"><strong>${esc(operation.action)} ${esc(basename(name))}</strong><small>${esc(progress)}${operation.non_atomic ? (operation.state === 'completed' ? ' · verified transfer' : ' · cross-location transfer') : ''}</small>${operation.error_code ? `<span class="files-operation-error" role="status">${esc(operation.error_code)}</span>` : ''}</span>
        <span class="files-operation-actions">
          ${operation.can_run ? '<button class="files-text-button" type="button" data-operation-action="run">start</button>' : ''}
          ${operation.can_cancel ? '<button class="files-text-button" type="button" data-operation-action="cancel">cancel</button>' : ''}
          ${operation.can_retry ? '<button class="files-text-button" type="button" data-operation-action="retry">retry</button>' : ''}
          ${operation.can_discard ? '<button class="files-text-button" type="button" data-operation-action="discard">dismiss</button>' : ''}
          ${operation.can_undo ? '<button class="files-text-button" type="button" data-operation-action="undo">undo</button>' : ''}
        </span>
      </div>`;
  };
  host.innerHTML = active.map(renderRow).join('')
    + `<div id="files-completed-list"${state.hiddenCompleted ? ' hidden' : ''}>${state.hiddenCompleted ? '' : history.map(renderRow).join('')}</div>`;
  if (focusedId && focusedAction && document.activeElement === document.body) {
    const replacement = host.querySelector(`[data-operation-id="${CSS.escape(focusedId)}"] [data-operation-action="${CSS.escape(focusedAction)}"]`);
    if (replacement) replacement.focus({ preventScroll: true });
    else if (toggle && !toggle.hidden) toggle.focus({ preventScroll: true });
  }
  updateOperationClearance();
}

async function operationAction(id, action) {
  try {
    const target = action === 'discard'
      ? `/api/files/operations/${encodeURIComponent(id)}`
      : `/api/files/operations/${encodeURIComponent(id)}/${action}`;
    await request(target, { method: action === 'discard' ? 'DELETE' : 'POST' });
    await Promise.all([
      loadOperations(),
      refreshAfterOperation(),
    ]);
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function undoOperation(id) {
  return operationAction(id, 'undo');
}

function showNotice(message, persistent = false) {
  const note = $('files-partial-note');
  if (!note) return;
  note.textContent = message || '';
  note.hidden = !message;
  if (message && !persistent) setTimeout(() => {
    if (note.textContent === message) note.hidden = true;
  }, 4500);
}

function openLocationDialog() {
  $('files-location-form')?.reset();
  choose($('files-location-kind'), 'local');
  choose($('files-location-access'), 'read_only');
  choose($('files-vault-workflow'), 'keep');
  resetVaultReview();
  renderLocationFields('local');
  $('files-location-error').textContent = '';
  openFilesDialog('location', '#files-location-name');
}

function renderLocationFields(kind) {
  const host = $('files-location-fields');
  if (!host) return;
  const vault = kind === 'obsidian';
  $('files-location-access-field').hidden = vault;
  $('files-vault-workflow-field').hidden = !vault;
  resetVaultReview();
  if (kind === 'local') {
    host.innerHTML = '<label>folder path<input id="files-location-root" autocomplete="off" placeholder="/absolute/path" required></label>';
  } else if (kind === 'obsidian') {
    host.innerHTML = '<label>existing vault folder<input id="files-location-root" autocomplete="off" placeholder="/absolute/path/to/vault" required></label><p class="files-vault-help">Alles checks every file, space requirement, destination conflict, and rollback copy before switching Docs.</p>';
  } else if (kind === 'webdav') {
    host.innerHTML = `
      <label>endpoint<input id="files-location-endpoint" autocomplete="url" placeholder="https://server.example/dav" required></label>
      <label>username<input id="files-location-username" autocomplete="username"></label>
      <label>password<input id="files-location-password" type="password" autocomplete="new-password"></label>`;
  } else {
    host.innerHTML = `
      <label>endpoint<input id="files-location-endpoint" autocomplete="url" placeholder="https://s3.example" required></label>
      <label>bucket<input id="files-location-bucket" autocomplete="off" required></label>
      <label>prefix<input id="files-location-prefix" autocomplete="off"></label>
      <label>region<input id="files-location-region" autocomplete="off"></label>
      <label>access key<input id="files-location-access-key" autocomplete="off" required></label>
      <label>secret key<input id="files-location-secret-key" type="password" autocomplete="new-password" required></label>`;
  }
}

function resetVaultReview() {
  state.vaultReviewSignature = '';
  state.vaultReview = null;
  const review = $('files-vault-review');
  if (review) { review.hidden = true; review.replaceChildren(); }
  const submit = $('files-location-submit');
  if (submit) { submit.textContent = 'add location'; submit.disabled = false; }
}

function chosen(host) {
  return host?.querySelector('[role="radio"][aria-checked="true"]')?.dataset.value || '';
}

function choose(host, value) {
  host?.querySelectorAll('[role="radio"]').forEach(button => {
    const selected = button.dataset.value === value;
    button.setAttribute('aria-checked', String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
}

async function createLocation() {
  const selectedKind = chosen($('files-location-kind'));
  let kind = selectedKind;
  let access = chosen($('files-location-access'));
  let rootPath = $('files-location-root')?.value.trim() || '';
  let vaultTransferId = '';
  if (selectedKind === 'obsidian') {
    const workflow = chosen($('files-vault-workflow')) || 'keep';
    const importBody = {
      source: rootPath,
      name: $('files-location-name').value.trim(),
      workflow,
    };
    const signature = JSON.stringify(importBody);
    if (state.vaultReviewSignature !== signature) {
      try {
        const preview = await request('/api/vault-transfer/import/preview', jsonOptions('POST', importBody));
        state.vaultReviewSignature = signature;
        state.vaultReview = preview;
        const review = $('files-vault-review');
        review.hidden = false;
        const conflict = preview.conflicts?.length
          ? `${preview.conflicts.length} destination conflict - choose a different name`
          : 'no destination conflicts';
        const storage = workflow === 'keep'
          ? 'no additional storage required'
          : `${formatSize(preview.required_bytes)} required · ${formatSize(preview.available_bytes)} available`;
        review.innerHTML = `<strong>${esc(preview.source_files)} files · ${esc(formatSize(preview.source_bytes) || '0 B')}</strong><span>${esc(conflict)}</span><span>${esc(storage)}</span><span>relative links and file bytes stay unchanged</span>${workflow === 'move' ? '<span>the source is removed only after the destination and rollback copy verify</span>' : ''}`;
        $('files-location-submit').textContent = preview.can_import ? (workflow === 'keep' ? 'keep external' : `${workflow} into Alles`) : 'review blocked';
        $('files-location-submit').disabled = !preview.can_import;
        if (!preview.can_import) $('files-location-error').textContent = conflict;
      } catch (error) {
        $('files-location-error').textContent = error.message;
      }
      return;
    }
    try {
      const transfer = await request('/api/vault-transfer/import', jsonOptions('POST', importBody));
      vaultTransferId = transfer.id;
      rootPath = transfer.destination;
      kind = 'local';
      access = workflow === 'keep' ? 'read_only' : 'managed';
    } catch (error) {
      $('files-location-error').textContent = error.message;
      return;
    }
  }
  const body = {
    name: $('files-location-name').value.trim(),
    kind,
    access,
    root_path: rootPath,
    endpoint: $('files-location-endpoint')?.value.trim() || '',
    bucket: $('files-location-bucket')?.value.trim() || '',
    prefix: $('files-location-prefix')?.value.trim() || '',
    config: {},
    credentials: {},
  };
  if (kind === 'webdav') {
    body.credentials = {
      username: $('files-location-username')?.value || '',
      password: $('files-location-password')?.value || '',
    };
  }
  if (kind === 's3') {
    body.config = { region: $('files-location-region')?.value.trim() || '' };
    body.credentials = {
      access_key_id: $('files-location-access-key')?.value || '',
      secret_access_key: $('files-location-secret-key')?.value || '',
    };
  }
  try {
    const location = await request('/api/storage-locations', jsonOptions('POST', body));
    closeDialog('location');
    state.locationId = location.id;
    state.cwd = '';
    await loadLocations();
    await loadFiles('');
  } catch (error) {
    let message = error.message;
    if (vaultTransferId) {
      try {
        await request(`/api/vault-transfer/${encodeURIComponent(vaultTransferId)}/rollback`, { method: 'POST' });
        message = `${message}. the vault change was rolled back`;
      } catch (rollbackError) {
        message = `${message}. vault rollback also failed: ${rollbackError.message}`;
      }
    }
    $('files-location-error').textContent = message;
  }
}

async function testLocation() {
  const location = currentLocation();
  if (!location) return;
  const locationId = location.id;
  renderLocationStatus('testing connection');
  try {
    const result = await request(`/api/storage-locations/${encodeURIComponent(locationId)}/test`, { method: 'POST' });
    if (locationId !== state.locationId) return;
    renderLocationStatus(result.ok ? 'ready' : (result.error || result.state || 'unavailable'));
  } catch (error) {
    if (locationId !== state.locationId) return;
    renderLocationStatus(error.message);
  }
}

async function changeLocationAccess() {
  const location = currentLocation();
  if (!location || location.is_default) return;
  const access = location.access === 'managed' ? 'read_only' : 'managed';
  try {
    await request(`/api/storage-locations/${encodeURIComponent(location.id)}`, jsonOptions('PATCH', { access }));
    await loadLocations();
    applyWriteState();
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function removeLocation() {
  const location = currentLocation();
  if (!location || location.is_default) return;
  const locationId = location.id;
  const ok = await dlgConfirm(`remove the location "${location.name}"? files are not deleted.`);
  if (!ok) return;
  try {
    await request(`/api/storage-locations/${encodeURIComponent(locationId)}`, { method: 'DELETE' });
    if (state.locationId !== locationId) {
      await loadLocations();
      return;
    }
    closeDialog('settings');
    state.locationId = '';
    state.cwd = '';
    await loadLocations();
    await loadFiles('');
  } catch (error) {
    toast(error.message, 'error');
  }
}

function dialogFocusables(dialog) {
  return [...dialog.querySelectorAll('a[href], button, input, textarea, audio[controls], video[controls], iframe, [tabindex]:not([tabindex="-1"])')]
    .filter(element => !element.disabled && !element.hidden);
}

function openFilesDialog(name, focusSelector) {
  const dialog = $(`files-${name}-dialog`);
  if (!dialog) return;
  dialogReturnFocus.set(name, document.activeElement);
  dialog.hidden = false;
  const background = [];
  for (let branch = dialog; branch.parentElement; branch = branch.parentElement) {
    for (const sibling of branch.parentElement.children) {
      if (sibling === branch || sibling.inert) continue;
      background.push(sibling);
      sibling.inert = true;
    }
    if (branch.parentElement === document.body) break;
  }
  dialogBackground.set(name, background);
  (dialog.querySelector(focusSelector) || dialogFocusables(dialog)[0])?.focus();
}

function trapFilesDialogFocus(event, dialog) {
  if (event.key !== 'Tab') return;
  const focusable = dialogFocusables(dialog);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
    event.preventDefault();
    first.focus();
  }
}

function closeDialog(name, restoreFocus = true) {
  const dialog = $(`files-${name}-dialog`);
  if (!dialog || dialog.hidden) return;
  dialog.hidden = true;
  dialogBackground.get(name)?.forEach(element => { element.inert = false; });
  dialogBackground.delete(name);
  if (restoreFocus) dialogReturnFocus.get(name)?.focus?.();
  dialogReturnFocus.delete(name);
}

export function closeFilesDialogs() {
  for (const name of [...dialogReturnFocus.keys()].reverse()) closeDialog(name, false);
}

async function searchFiles(term) {
  const q = term.trim();
  state.searchTerm = q;
  if (!q) {
    searchSequence += 1;
    return loadCurrentView();
  }
  if (state.view === 'starred') {
    searchSequence += 1;
    filterCurrentItems(q);
    renderItems();
    renderSelection();
    showNotice(`${state.items.length} starred result${state.items.length === 1 ? '' : 's'}`);
    return;
  }
  if (state.view === 'offline') {
    searchSequence += 1;
    filterOfflineItems(q);
    renderItems();
    renderSelection();
    showNotice(`${state.items.length} cached result${state.items.length === 1 ? '' : 's'}`);
    return;
  }
  const searchingTrash = state.view === 'trash';
  const host = $('files-list');
  viewSequence += 1;
  const sequence = ++searchSequence;
  const locationId = state.locationId;
  const view = state.view;
  const cwd = state.cwd;
  showNotice('');
  beginFilesRequest(host);
  try {
    const data = await request('/api/files/search' + query({ q, location_id: locationId }));
    if (sequence !== searchSequence || locationId !== state.locationId || view !== state.view) return;
    if (cwd !== state.cwd) return;
    if (searchingTrash) {
      state.view = 'all';
      state.cwd = '';
      state.selected.clear();
      state.current = null;
      syncViewButtons();
      renderBreadcrumb();
    }
    state.items = data.results || [];
    renderItems();
    renderSelection();
    showNotice(`${state.items.length} result${state.items.length === 1 ? '' : 's'}`);
  } catch (error) {
    if (sequence !== searchSequence || locationId !== state.locationId || view !== state.view) return;
    if (cwd !== state.cwd) return;
    state.items = [];
    state.viewItems = [];
    state.selected.clear();
    renderSelection();
    renderFilesError(host, error, () => searchFiles(q));
  }
}

function filterCurrentItems(term) {
  const needle = String(term || '').trim().toLocaleLowerCase();
  state.items = needle
    ? state.viewItems.filter(item => (
      `${item.name || ''} ${item.path || item.normalized_path || ''}`
        .toLocaleLowerCase()
        .includes(needle)
    ))
    : [...state.viewItems];
  reconcileSelectionWithVisibleItems();
}

function filterOfflineItems(term) {
  filterCurrentItems(term);
}

function reconcileSelectionWithVisibleItems() {
  const visible = new Set(state.items.map(itemKey));
  for (const key of state.selected.keys()) {
    if (!visible.has(key)) state.selected.delete(key);
  }
}

function clearFilesSearch() {
  clearTimeout(searchTimer);
  searchSequence += 1;
  state.searchTerm = '';
  const input = $('files-search');
  if (input) input.value = '';
}

async function newFolder() {
  if (!isWritable()) return;
  const name = await dlgPrompt('new folder name:');
  if (!name) return;
  try {
    await request('/api/files/mkdir', jsonOptions('POST', {
      location_id: state.locationId,
      path: joinPath(state.cwd, name),
    }));
    await loadFiles(state.cwd);
  } catch (error) {
    toast(error.message, 'error');
  }
}

function sendUpload(file, name, locationId, cwd, expected = '') {
  const body = new FormData();
  body.append('location_id', locationId);
  body.append('path', cwd);
  body.append('file', file, name);
  if (expected) body.append('expected_etag', expected);
  return request('/api/files/upload', { method: 'POST', body });
}

function reviewUpload(file, locationId, cwd, initialError) {
  return new Promise(resolve => {
    const previousFocus = document.activeElement;
    const overlay = document.createElement('div');
    overlay.className = 'dialog-overlay files-upload-review';
    const locationName = state.locations.find(location => location.id === locationId)?.name || 'files';
    overlay.innerHTML = `<form class="dialog-card" role="dialog" aria-modal="true" aria-labelledby="files-upload-review-title" aria-describedby="files-upload-review-message">
      <h2 id="files-upload-review-title">finish upload</h2>
      <p class="files-upload-destination">${esc([locationName, cwd].filter(Boolean).join(' / '))}</p>
      <p id="files-upload-review-message" role="alert" tabindex="-1"></p>
      <label for="files-upload-review-name">file name</label>
      <input id="files-upload-review-name" class="settings-input" value="${esc(file.name)}" autocomplete="off">
      <div class="dialog-btns">
        <button type="button" class="btn" data-upload-cancel>cancel upload</button>
        <button type="submit" class="btn primary" data-upload-submit>retry upload</button>
      </div>
    </form>`;
    document.body.appendChild(overlay);
    const form = overlay.querySelector('form');
    const input = overlay.querySelector('input');
    const message = overlay.querySelector('#files-upload-review-message');
    const submit = overlay.querySelector('[data-upload-submit]');
    const cancel = overlay.querySelector('[data-upload-cancel]');
    let error = initialError;
    let reviewedName = file.name;
    let busy = false;
    const finish = value => {
      overlay.remove();
      (previousFocus?.isConnected ? previousFocus : $('files-upload-btn'))?.focus();
      resolve(value);
    };
    const update = () => {
      const sameName = input.value.trim() === reviewedName;
      const collision = error.detail?.code === 'file_conflict';
      const replace = sameName && collision && error.detail.can_replace;
      const valid = Boolean(input.value.trim()) && !input.value.includes('/') && !input.value.includes('\\') && !/^\.+$/.test(input.value.trim());
      message.textContent = error.message + (replace ? '. The current file will be kept in version history.' : '');
      submit.textContent = replace ? 'replace file' : sameName ? 'retry upload' : 'upload with new name';
      submit.disabled = busy || !valid || (sameName && collision && !error.detail.can_replace);
      input.disabled = cancel.disabled = busy;
    };
    input.addEventListener('input', update);
    cancel.addEventListener('click', () => { if (!busy) finish(false); });
    overlay.addEventListener('click', event => { if (event.target === overlay && !busy) finish(false); });
    overlay.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        event.preventDefault(); event.stopPropagation();
        if (!busy) finish(false);
      } else if (event.key === 'Tab') {
        trapFilesDialogFocus(event, form);
        event.stopPropagation();
      }
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (submit.disabled || busy) return;
      const name = input.value.trim();
      const expected = name === reviewedName && error.detail?.code === 'file_conflict'
        ? error.detail.expected_etag : '';
      busy = true;
      update();
      message.textContent = `uploading ${name}…`;
      try {
        await sendUpload(file, name, locationId, cwd, expected);
        finish(true);
      } catch (nextError) {
        error = nextError;
        reviewedName = name;
        busy = false;
        update();
        message.focus();
      }
    });
    update();
    cancel.focus();
  });
}

async function uploadFiles(files) {
  if (!isWritable()) return;
  if (uploadActive) { toast('finish the current upload first', 'error'); return; }
  uploadActive = true;
  const button = $('files-upload-btn');
  const locationId = state.locationId;
  const cwd = state.cwd;
  let complete = 0;
  if (button) { button.disabled = true; button.textContent = 'uploading…'; button.setAttribute('aria-busy', 'true'); }
  try {
    for (const file of files) {
      try {
        await sendUpload(file, file.name, locationId, cwd);
        complete += 1;
      } catch (error) {
        if (await reviewUpload(file, locationId, cwd, error)) complete += 1;
      }
    }
    if (complete) {
      toast(`${complete} file${complete === 1 ? '' : 's'} uploaded`, 'success');
      if (state.locationId === locationId && state.cwd === cwd) await loadFiles(cwd);
    }
  } finally {
    uploadActive = false;
    if (button) {
      button.textContent = 'upload'; button.removeAttribute('aria-busy'); button.disabled = !isWritable();
      if (document.activeElement === document.body && button.offsetParent) button.focus();
    }
  }
}

function wireChoiceGroup(host, onChange) {
  host?.addEventListener('click', event => {
    const button = event.target.closest('[role="radio"]');
    if (!button) return;
    choose(host, button.dataset.value);
    onChange?.(button.dataset.value);
  });
  host?.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    const buttons = [...host.querySelectorAll('[role="radio"]')];
    const current = buttons.indexOf(document.activeElement);
    const step = ['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1;
    const next = event.key === 'Home' ? buttons[0] : event.key === 'End' ? buttons.at(-1)
      : buttons[(current + step + buttons.length) % buttons.length];
    event.preventDefault();
    next?.focus();
    next?.click();
  });
}

function revealFileControl(target) {
  const view = $('files-view');
  const header = $('files-app-header');
  const item = target?.closest('.files-location-button, .file-row');
  if (!view || !header || !item || !view.contains(item)
    || getComputedStyle(header).position !== 'sticky') return;
  const bounds = view.getBoundingClientRect();
  const top = Math.max(bounds.top + view.clientTop, header.getBoundingClientRect().bottom);
  const bottom = Math.min(innerHeight, bounds.top + view.clientTop + view.clientHeight);
  const rect = item.getBoundingClientRect();
  const topDelta = rect.top - top;
  const bottomDelta = rect.bottom - bottom;
  if (topDelta < 0 && bottomDelta < 0) {
    view.scrollTop += Math.max(topDelta, bottomDelta);
  } else if (topDelta > 0 && bottomDelta > 0) {
    view.scrollTop += Math.min(topDelta, bottomDelta);
  }
}

function revealHorizontalFileControl(event) {
  const button = event.target.closest('button');
  if (!button || !button.matches(':focus-visible')) return;
  const scroller = button.closest('#files-breadcrumb, .files-phase7-location-panel');
  if (!scroller || !['auto', 'scroll'].includes(getComputedStyle(scroller).overflowX)) return;
  const bounds = scroller.getBoundingClientRect();
  const rect = button.getBoundingClientRect();
  const style = getComputedStyle(button);
  const inset = Math.max(0, (parseFloat(style.outlineWidth) || 0) + (parseFloat(style.outlineOffset) || 0));
  const left = bounds.left + scroller.clientLeft + inset;
  const right = left + scroller.clientWidth - 2 * inset;
  const leftDelta = rect.left - left;
  const rightDelta = rect.right - right;
  if (leftDelta < 0 && rightDelta < 0) {
    scroller.scrollLeft += Math.max(leftDelta, rightDelta);
  } else if (leftDelta > 0 && rightDelta > 0) {
    scroller.scrollLeft += Math.min(leftDelta, rightDelta);
  }
}

function bindEvents() {
  $('files-view')?.addEventListener('focusin', event => revealFileControl(event.target));
  $('files-breadcrumb')?.addEventListener('focusin', revealHorizontalFileControl);
  document.querySelector('.files-phase7-location-panel')?.addEventListener('focusin', revealHorizontalFileControl);
  $('files-settings-btn')?.addEventListener('click', () => {
    renderLocationStatus();
    openFilesDialog('settings', '[data-files-dialog-close]');
  });
  $('files-add-location')?.addEventListener('click', openLocationDialog);
  $('files-location-list')?.addEventListener('click', async event => {
    const button = event.target.closest('[data-location-id]');
    if (!button || button.dataset.locationId === state.locationId) return;
    closeDetails();
    state.locationId = button.dataset.locationId;
    state.cwd = '';
    state.view = 'all';
    state.selected.clear();
    clearFilesSearch();
    renderLocations();
    renderLocationStatus();
    const listing = loadFiles('');
    void loadIndexStatus(state.locationId);
    await listing;
  });
  $('files-location-status')?.addEventListener('click', event => {
    const action = event.target.closest('[data-location-action]')?.dataset.locationAction;
    if (action === 'test') testLocation();
    if (action === 'index') startIndexing();
    if (action === 'access') changeLocationAccess();
    if (action === 'remove') removeLocation();
  });
  document.querySelector('.files-phase7-views')?.addEventListener('click', event => {
    const button = event.target.closest('[data-files-view]');
    if (!button) return;
    state.view = button.dataset.filesView;
    state.cwd = '';
    state.selected.clear();
    clearFilesSearch();
    renderSelection();
    syncViewButtons();
    loadCurrentView();
  });
  $('files-breadcrumb')?.addEventListener('click', event => {
    const button = event.target.closest('[data-crumb-path]');
    if (!button) return;
    if (state.view === 'offline') {
      state.cwd = button.dataset.crumbPath;
      loadCurrentView();
    } else {
      loadFiles(button.dataset.crumbPath);
    }
  });
  $('files-up-btn')?.addEventListener('click', () => {
    if (state.view === 'offline') {
      state.cwd = state.cwd.includes('/') ? state.cwd.slice(0, state.cwd.lastIndexOf('/')) : '';
      return loadCurrentView();
    }
    if (state.view !== 'all') return loadFiles('');
    const parent = state.cwd.includes('/') ? state.cwd.slice(0, state.cwd.lastIndexOf('/')) : '';
    loadFiles(parent);
  });
  $('files-list')?.addEventListener('click', event => {
    if (event.target.closest('[data-files-retry]')) {
      const retry = filesRetry;
      filesRetry = null;
      retry?.();
      return;
    }
    const row = event.target.closest('.file-row');
    if (!row) return;
    const item = findItem(row.dataset.path);
    if (event.target.closest('[data-file-select]')) toggleSelection(row.dataset.path);
    else if (event.target.closest('[data-file-open]')) openItem(item);
    else renderDetails(item);
  });
  $('files-list')?.addEventListener('dblclick', event => {
    if (event.target.closest('button, input, textarea, [role="button"], [data-file-select], [data-file-open]')) return;
    const row = event.target.closest('.file-row');
    if (!row) return;
    const item = findItem(row.dataset.path);
    if (item?.type === 'dir') openItem(item);
    else openPreview(item);
  });
  $('files-list')?.addEventListener('keydown', event => {
    const row = event.target.closest('.file-row');
    if (!row || event.target !== row || ![' ', 'Enter'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === ' ') toggleSelection(row.dataset.path);
    else openItem(findItem(row.dataset.path));
  });
  $('files-select-all')?.addEventListener('click', selectAll);
  $('files-selection-bar')?.addEventListener('click', async event => {
    const button = event.target.closest('[data-files-bulk]');
    const action = button?.dataset.filesBulk;
    if (state.view === 'trash' && !['restore', 'clear'].includes(action)) return;
    if (action === 'restore') {
      if (state.view !== 'trash' || !isWritable() || state.selected.size !== 1 || selectionRestoreActive) return;
      const [key, item] = [...state.selected.entries()][0];
      const locationId = state.locationId;
      const sequence = viewSequence;
      selectionRestoreActive = true;
      applyWriteState();
      try {
        const operation = await restoreItem(item, { close: false });
        if (operation && state.locationId === locationId && state.view === 'trash'
            && viewSequence === sequence && state.selected.size === 1 && state.selected.get(key) === item) {
          const restoreFocus = document.activeElement === button;
          state.selected.clear(); renderItems(); renderSelection();
          if (restoreFocus) document.querySelector('[data-files-view="trash"]')?.focus();
        }
      } finally {
        selectionRestoreActive = false;
        applyWriteState();
      }
    }
    if (action === 'copy' || action === 'move') openTransferDialog(action);
    if (action === 'offline') await keepItemsOffline([...state.selected.values()]);
    if (action === 'delete') deleteItems([...state.selected.values()]);
    if (action === 'clear') { state.selected.clear(); renderItems(); renderSelection(); }
  });
  $('files-detail-close')?.addEventListener('click', closeDetails);
  $('files-detail-content')?.addEventListener('click', event => {
    const action = event.target.closest('[data-detail-action]')?.dataset.detailAction;
    const item = state.current;
    if (!action || !item) return;
    if (action === 'open') {
      if (item.type === 'dir') {
        closeDetails();
        openItem(item);
      } else {
        openPreview(item);
      }
    }
    if (action === 'offline') toggleOffline(item);
    if (action === 'offline-refresh') setOffline(item, 'keep');
    if (action === 'offline-remove') setOffline(item, 'remove');
    if (action === 'star') setStar(item);
    if (action === 'rename') renameItem(item);
    if (action === 'delete') deleteItems([item]);
    if (action === 'restore') restoreItem(item);
    if (action === 'photos') sendToPhotos(item);
  });
  $('files-operation-list')?.addEventListener('click', event => {
    const button = event.target.closest('[data-operation-action]');
    const row = event.target.closest('[data-operation-id]');
    if (!button || !row) return;
    if (button.dataset.operationAction === 'undo') undoOperation(row.dataset.operationId);
    else operationAction(row.dataset.operationId, button.dataset.operationAction);
  });
  $('files-operations-clear')?.addEventListener('click', () => {
    state.hiddenCompleted = !state.hiddenCompleted;
    renderOperations();
  });
  $('files-mkdir-btn')?.addEventListener('click', newFolder);
  $('files-upload-btn')?.addEventListener('click', () => $('files-upload-input')?.click());
  $('files-upload-input')?.addEventListener('change', event => {
    uploadFiles([...event.target.files]);
    event.target.value = '';
  });
  $('files-search')?.addEventListener('input', event => {
    clearTimeout(searchTimer);
    state.searchTerm = event.target.value.trim();
    searchTimer = setTimeout(() => searchFiles(event.target.value), 260);
  });
  $('files-preview-close')?.addEventListener('click', closePreview);
  $('files-preview-modal')?.addEventListener('click', event => {
    const previewModal = event.currentTarget;
    if (event.target === previewModal) closePreview();
  });
  document.querySelectorAll('[data-files-dialog-close]').forEach(button => {
    button.addEventListener('click', () => closeDialog(button.dataset.filesDialogClose));
  });
  $('files-location-form')?.addEventListener('submit', event => {
    event.preventDefault();
    createLocation();
  });
  $('files-location-form')?.addEventListener('input', event => {
    if (event.target.matches('input') && chosen($('files-location-kind')) === 'obsidian') {
      resetVaultReview();
      $('files-location-error').textContent = '';
    }
  });
  $('files-transfer-form')?.addEventListener('submit', event => {
    event.preventDefault();
    submitTransfer().catch(error => { $('files-transfer-error').textContent = error.message; });
  });
  wireChoiceGroup($('files-location-kind'), renderLocationFields);
  wireChoiceGroup($('files-location-access'), resetVaultReview);
  wireChoiceGroup($('files-vault-workflow'), resetVaultReview);
  wireChoiceGroup($('files-transfer-locations'));
  document.addEventListener('keydown', event => {
    if (event.defaultPrevented || event.target.closest?.('.dialog-overlay')) return;
    const previewModal = $('files-preview-modal');
    if (previewModal?.style.display !== 'none' && event.key === 'Tab') {
      trapFilesDialogFocus(event, previewModal);
      return;
    }
    const openDialog = ['transfer', 'location', 'settings']
      .map(name => $(`files-${name}-dialog`))
      .find(dialog => dialog && !dialog.hidden);
    if (openDialog && event.key === 'Tab') {
      trapFilesDialogFocus(event, openDialog);
      return;
    }
    if (event.key !== 'Escape') return;
    if (previewModal?.style.display !== 'none') closePreview();
    else if (!$('files-transfer-dialog')?.hidden) closeDialog('transfer');
    else if (!$('files-location-dialog')?.hidden) closeDialog('location');
    else if (!$('files-settings-dialog')?.hidden) closeDialog('settings');
    else if (!$('files-detail-panel')?.hidden) closeDetails();
  });
}

export function initFiles(fetcher = fetch) {
  if (initialized) return loadOperations(fetcher);
  initialized = true;
  const params = new URLSearchParams(location.search);
  state.cwd = params.get('p') || '';
  state.locationId = params.get('location') || '';
  state.sort = ['name', 'size', 'mtime', 'type'].includes(params.get('sort'))
    ? params.get('sort') : 'name';
  state.order = ['asc', 'desc'].includes(params.get('order')) ? params.get('order') : '';
  bindEvents();
  const dock = $('files-operation-dock');
  const dockObserver = typeof ResizeObserver === 'function' ? new ResizeObserver(updateOperationClearance) : null;
  if (dock) dockObserver?.observe(dock);
  const header = $('files-app-header');
  if (header) dockObserver?.observe(header);
  window.addEventListener('resize', updateOperationClearance);
  const initialOperations = loadOperations(fetcher);
  operationPoll = window.setInterval(pollOperations, 4000);
  window.addEventListener('beforeunload', () => {
    clearInterval(operationPoll);
    clearTimeout(indexPoll);
    dockObserver?.disconnect();
    window.removeEventListener('resize', updateOperationClearance);
  }, { once: true });
  return initialOperations;
}

import { toast } from './util.js';
import { prompt as dlgPrompt, confirm as dlgConfirm } from './dialog.js';
import { formatDate } from './i18n.js';

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
  hiddenCompleted: false,
  indexStatus: new Map(),
  searchTerm: '',
  vaultReviewSignature: '',
  vaultReview: null,
};

let initialized = false;
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
    const message = typeof data === 'object' ? data.detail : data;
    throw new Error(message || `request failed (${response.status})`);
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
    history.replaceState(null, '', url);
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
  const kind = location.kind === 'local' ? 'local' : location.kind.toUpperCase();
  host.textContent = `${kind} · ${location.access === 'managed' ? 'managed' : 'read only'}`;
}

function renderLocationStatus(message = '') {
  const host = $('files-location-status');
  const location = currentLocation();
  if (!location) {
    renderAppStatus(null, { state: 'idle' });
    if (host) host.textContent = '';
    return;
  }
  const index = state.indexStatus.get(location.id) || { state: 'idle', files_indexed: 0 };
  renderAppStatus(location, index);
  if (!host) return;
  const indexing = ['queued', 'running'].includes(index.state);
  const indexCopy = indexing
    ? `indexing${index.files_indexed ? ` · ${index.files_indexed} files` : ''}`
    : index.state === 'completed'
      ? `${index.files_indexed} files indexed`
      : index.state === 'error'
        ? (index.error || 'indexing failed')
        : 'not indexed yet';
  host.innerHTML = `
    <div>${esc(message || locationLabel(location))}</div>
    <div class="files-location-index-state">${esc(indexCopy)}</div>
    <div>
      <button class="files-text-button" type="button" data-location-action="test">test</button>
      <button class="files-text-button" type="button" data-location-action="index"${indexing ? ' disabled' : ''}>${index.state === 'completed' ? 'reindex' : 'index'}</button>
      ${location.is_default ? '' : '<button class="files-text-button" type="button" data-location-action="access">change access</button>'}
      ${location.is_default ? '' : '<button class="files-text-button files-danger" type="button" data-location-action="remove">remove</button>'}
    </div>`;
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
    renderLocationStatus(error.message);
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
    button.hidden = (trashView && action !== 'clear')
      || (cacheView && !['offline', 'clear'].includes(action));
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
      <dt>size</dt><dd>${esc(formatSize(item.size) || 'unknown')}</dd>
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
  try {
    const versions = await request('/api/files/versions' + query({ path, location_id: locationId }));
    if (detailRequest !== detailSequence
      || locationId !== state.locationId
      || state.current !== item
      || panel.hidden) return;
    if (!versions.length) return;
    host.innerHTML = `<dl class="files-detail-meta"><dt>versions</dt><dd>${versions.length}</dd></dl>`;
  } catch {}
}

function closeDetails() {
  detailSequence += 1;
  const returnPath = state.detailReturnPath;
  const panel = $('files-detail-panel');
  const wasOpen = Boolean(panel && !panel.hidden);
  state.current = null;
  if (panel) panel.hidden = true;
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
  const ok = await dlgConfirm(`move ${items.length} item${items.length === 1 ? '' : 's'} to recently deleted?`);
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

async function restoreItem(item) {
  if (!isWritable()) return;
  try {
    await queueOperation({
      action: 'restore',
      source_location_id: state.locationId,
      source_path: item.trash_id,
    });
    closeDetails();
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
  try {
    const result = await request('/api/files/to-photos', jsonOptions('POST', {
      location_id: state.locationId,
      path: item.path || item.normalized_path,
    }));
    toast(photosImportMessage(result), result.failed?.length ? 'error' : 'success');
  } catch (error) {
    toast(error.message, 'error');
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

function renderOperations() {
  const dock = $('files-operation-dock');
  const host = $('files-operation-list');
  if (!dock || !host) return;
  const visible = state.operations.filter(operation => !(state.hiddenCompleted && operation.state === 'completed'));
  dock.hidden = visible.length === 0;
  host.innerHTML = visible.map(operation => {
    const progress = operation.bytes_total
      ? `${Math.min(100, Math.round((operation.bytes_done / operation.bytes_total) * 100))}%`
      : operation.state;
    return `
      <div class="files-operation-row" data-operation-id="${esc(operation.id)}">
        <span class="files-operation-copy"><strong>${esc(operation.action)} ${esc(basename(operation.source_path))}</strong><small>${esc(progress)}${operation.non_atomic ? ' · verified transfer' : ''}${operation.error_code ? ` · ${esc(operation.error_code)}` : ''}</small></span>
        <span class="files-operation-actions">
          ${operation.can_run ? '<button class="files-text-button" type="button" data-operation-action="run">start</button>' : ''}
          ${operation.can_cancel ? '<button class="files-text-button" type="button" data-operation-action="cancel">cancel</button>' : ''}
          ${operation.can_retry ? '<button class="files-text-button" type="button" data-operation-action="retry">retry</button>' : ''}
          ${operation.can_discard ? '<button class="files-text-button" type="button" data-operation-action="discard">dismiss</button>' : ''}
          ${operation.can_undo ? '<button class="files-text-button" type="button" data-operation-action="undo">undo</button>' : ''}
        </span>
      </div>`;
  }).join('');
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

function closeDialog(name) {
  const dialog = $(`files-${name}-dialog`);
  if (dialog) dialog.hidden = true;
  dialogReturnFocus.get(name)?.focus?.();
  dialogReturnFocus.delete(name);
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

async function uploadFiles(files) {
  if (!isWritable()) return;
  const locationId = state.locationId;
  const cwd = state.cwd;
  let complete = 0;
  for (const file of files) {
    const body = new FormData();
    body.append('location_id', locationId);
    body.append('path', cwd);
    body.append('file', file);
    try {
      await request('/api/files/upload', { method: 'POST', body });
      complete += 1;
    } catch (error) {
      toast(`${file.name}: ${error.message}`, 'error');
    }
  }
  if (complete) {
    toast(`${complete} file${complete === 1 ? '' : 's'} uploaded`, 'success');
    if (state.locationId === locationId && state.cwd === cwd) await loadFiles(cwd);
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

function bindEvents() {
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
    const action = event.target.closest('[data-files-bulk]')?.dataset.filesBulk;
    if (state.view === 'trash' && action !== 'clear') return;
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
    $('files-operations-clear').textContent = state.hiddenCompleted ? 'show completed' : 'hide completed';
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
    const previewModal = $('files-preview-modal');
    if (previewModal?.style.display !== 'none' && event.key === 'Tab') {
      trapFilesDialogFocus(event, previewModal);
      return;
    }
    const openDialog = ['transfer', 'location']
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
    else if (!$('files-detail-panel')?.hidden) closeDetails();
  });
}

export function initFiles(fetcher = fetch) {
  if (initialized) return loadOperations(fetcher);
  initialized = true;
  const params = new URLSearchParams(location.search);
  state.cwd = params.get('p') || '';
  state.locationId = params.get('location') || '';
  bindEvents();
  const initialOperations = loadOperations(fetcher);
  operationPoll = window.setInterval(pollOperations, 4000);
  window.addEventListener('beforeunload', () => {
    clearInterval(operationPoll);
    clearTimeout(indexPoll);
  }, { once: true });
  return initialOperations;
}

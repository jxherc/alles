import { createSettingsPane } from './pane.js';
import { toast } from '../util.js';
import { confirm as _dlgConfirm } from '../dialog.js';
import { populateDropdown } from '../dropdown.js?v=212';
import { formatDateTime } from '../i18n.js';
import { _confirmRecentOwner, _fetchWithRecentOwner } from './shared.js';

// ── webdav backup ────────────────────────────────────────────────────────────
let _webdavConfigured = false;
let _webdavBackups = [];
let _webdavLoadGeneration = 0;
let _webdavListGeneration = 0;
let _webdavDraftRevision = 0;
let _webdavDirty = false;
let _webdavMutationPending = false;
let _webdavDeferredListLoad = null;

export function normalizeWebdavBackupConfig(payload = {}) {
  const value = payload && typeof payload.webdav === 'object' ? payload.webdav : payload;
  return {
    configured: value?.configured === true,
    url: String(value?.url || ''),
    username: String(value?.username || ''),
    last_backup_at: String(value?.last_backup_at || ''),
    last_verified_at: String(value?.last_verified_at || ''),
    last_filename: String(value?.last_filename || ''),
    last_bytes: Number.isFinite(Number(value?.last_bytes)) ? Number(value.last_bytes) : null,
    error: String(value?.error || ''),
  };
}

export function webdavBackupConfigPayload(url, username, password, hasSavedPassword = false) {
  const urlValue = String(url || '').trim();
  const usernameValue = String(username || '').trim();
  const passwordValue = String(password || '');
  if (!urlValue) throw new Error('add the WebDAV https url');
  let parsed;
  try { parsed = new URL(urlValue); } catch { throw new Error('enter a valid WebDAV url'); }
  if (parsed.protocol !== 'https:') throw new Error('the WebDAV url must use https');
  if (parsed.username || parsed.password) throw new Error('keep the username and password out of the url');
  if (!usernameValue) throw new Error('add the WebDAV username');
  if (!passwordValue && !hasSavedPassword) throw new Error('add the WebDAV password');
  const result = { url: parsed.toString(), username: usernameValue };
  if (passwordValue) result.password = passwordValue;
  return result;
}

export function webdavBackupsFromResponse(payload = {}) {
  const values = Array.isArray(payload) ? payload : payload?.backups;
  if (!Array.isArray(values)) return [];
  return values.map(value => {
    if (typeof value === 'string') return { filename: value, bytes: null, modified_at: '' };
    const bytes = Number(value?.bytes);
    return {
      filename: String(value?.filename || ''),
      bytes: Number.isFinite(bytes) && bytes >= 0 ? bytes : null,
      modified_at: String(value?.modified_at || ''),
    };
  }).filter(value => value.filename).sort((left, right) => {
    const leftTime = Date.parse(left.modified_at);
    const rightTime = Date.parse(right.modified_at);
    if (!Number.isFinite(leftTime) || !Number.isFinite(rightTime)) return 0;
    return rightTime - leftTime;
  });
}

function _formatWebdavTime(value) {
  if (!value) return 'never';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'unknown' : formatDateTime(date);
}

function _formatWebdavBytes(value) {
  if (!Number.isFinite(value) || value < 0) return '';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

async function _webdavResponseJson(response) {
  return response.json().catch(() => ({}));
}

function _webdavError(data, fallback, secrets = []) {
  let message = typeof data?.detail === 'string' && data.detail.trim() ? data.detail.trim() : fallback;
  for (const secret of secrets) {
    if (secret) message = message.split(secret).join('[hidden]');
  }
  return message;
}

function _setWebdavStatus(message, kind = '') {
  const status = document.getElementById('webdav-backup-status');
  if (!status) return;
  status.textContent = message;
  status.style.color = kind === 'error' ? 'var(--error)' : (kind === 'success' ? 'var(--green)' : 'var(--muted)');
}

function _setWebdavMutationPending(pending) {
  const wasPending = _webdavMutationPending;
  if (pending && !_webdavMutationPending) _webdavLoadGeneration += 1;
  _webdavMutationPending = pending;
  const save = document.getElementById('webdav-backup-save-btn');
  if (save) {
    save.disabled = pending;
    if (!pending) save.textContent = _webdavConfigured ? 'save connection' : 'connect and save';
  }
  const disconnect = document.getElementById('webdav-backup-disconnect-btn');
  if (disconnect) disconnect.disabled = pending || disconnect.hidden;
  const run = document.getElementById('webdav-backup-run-btn');
  if (run) {
    run.disabled = pending || !_webdavConfigured;
    if (!pending) run.textContent = 'back up now';
  }
  const select = document.getElementById('webdav-backup-list');
  if (select) select.disabled = pending || !_webdavConfigured || !_webdavBackups.length;
  const restore = document.getElementById('webdav-backup-restore-btn');
  if (restore) {
    restore.disabled = pending || !_webdavConfigured || !_webdavBackups.some(backup => backup.filename === select?.value);
    if (!pending) restore.textContent = 'verify and stage selected restore';
  }
  const refresh = document.getElementById('webdav-backup-refresh-btn');
  if (refresh) refresh.disabled = pending || !_webdavConfigured;
  for (const id of ['webdav-backup-recovery-key-btn', 'webdav-backup-recovery-key']) {
    const control = document.getElementById(id);
    if (control) control.disabled = pending;
  }
  if (wasPending && !pending) {
    const isCurrent = _webdavDeferredListLoad;
    _webdavDeferredListLoad = null;
    if (_webdavConfigured && isCurrent?.()) loadWebdavBackups(false, isCurrent);
  }
}

function _applyWebdavConfig(config, keepDraft = false) {
  const updateFields = !keepDraft || !_webdavDirty;
  _webdavConfigured = config.configured;
  const url = document.getElementById('webdav-backup-url');
  const username = document.getElementById('webdav-backup-username');
  const password = document.getElementById('webdav-backup-password');
  if (url && updateFields) url.value = config.url;
  if (username && updateFields) username.value = config.username;
  if (password && updateFields) password.value = '';
  const disconnect = document.getElementById('webdav-backup-disconnect-btn');
  if (disconnect) {
    disconnect.hidden = !config.configured && !config.error;
    disconnect.textContent = config.error ? 'remove broken settings' : 'disconnect';
  }
  _setWebdavMutationPending(_webdavMutationPending);
  const refresh = document.getElementById('webdav-backup-refresh-btn');
  if (refresh) refresh.disabled = _webdavMutationPending || !config.configured;
  const lastSuccess = document.getElementById('webdav-backup-last-success');
  if (lastSuccess) lastSuccess.textContent = _formatWebdavTime(config.last_backup_at);
  const lastVerified = document.getElementById('webdav-backup-last-verified');
  if (lastVerified) lastVerified.textContent = _formatWebdavTime(config.last_verified_at);
  if (!_webdavMutationPending) {
    if (config.error) _setWebdavStatus(config.error, 'error');
    else _setWebdavStatus(updateFields ? (config.configured ? 'connected' : 'not connected') : 'unsaved connection changes kept here', updateFields && config.configured ? 'success' : '');
  }
  if (!config.configured) renderWebdavBackups([]);
}

async function loadWebdavBackup(isCurrent = () => true) {
  if (!document.getElementById('webdav-backup-card')) return;
  if (_webdavMutationPending) { _webdavDeferredListLoad = isCurrent; return; }
  const generation = ++_webdavLoadGeneration;
  _setWebdavStatus('checking connection…');
  try {
    const response = await fetch('/api/backup/webdav');
    const data = await _webdavResponseJson(response);
    if (!response.ok) throw new Error(_webdavError(data, 'could not check WebDAV'));
    if (generation !== _webdavLoadGeneration || !isCurrent()) return;
    const config = normalizeWebdavBackupConfig(data);
    _applyWebdavConfig(config, true);
    if (config.configured) await loadWebdavBackups(false, isCurrent);
  } catch (error) {
    if (generation !== _webdavLoadGeneration || !isCurrent()) return;
    _webdavConfigured = false;
    _setWebdavStatus(error.message || 'could not check WebDAV', 'error');
    renderWebdavBackups([]);
  }
}

async function saveWebdavBackup() {
  if (_webdavMutationPending) return;
  const revision = _webdavDraftRevision;
  _webdavLoadGeneration += 1;
  const url = document.getElementById('webdav-backup-url');
  const username = document.getElementById('webdav-backup-username');
  const password = document.getElementById('webdav-backup-password');
  const button = document.getElementById('webdav-backup-save-btn');
  const passwordValue = password?.value || '';
  let payload;
  try {
    payload = webdavBackupConfigPayload(url?.value, username?.value, passwordValue, _webdavConfigured);
  } catch (error) {
    _setWebdavStatus(error.message, 'error');
    toast(error.message, 'error');
    return;
  }
  if (password) password.value = '';
  _setWebdavMutationPending(true);
  if (button) button.textContent = 'saving…';
  _setWebdavStatus('checking and saving…');
  try {
    const response = await _fetchWithRecentOwner('/api/backup/webdav', {
      method: 'PUT',
      headers: {'content-type':'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await _webdavResponseJson(response);
    if (!response.ok) throw new Error(_webdavError(data, 'WebDAV connection was not saved', [passwordValue]));
    const config = normalizeWebdavBackupConfig(data);
    if (revision === _webdavDraftRevision) _webdavDirty = false;
    _applyWebdavConfig(config, true);
    toast('WebDAV connection saved', 'success');
    const isCurrent = _webdavDeferredListLoad || (() => true);
    _webdavDeferredListLoad = null;
    await loadWebdavBackups(false, isCurrent);
    _setWebdavStatus(_webdavDirty ? 'saved; newer connection edits kept here' : 'connected and saved', 'success');
  } catch (error) {
    _setWebdavStatus(error.message || 'WebDAV connection was not saved', 'error');
    toast(error.message || 'WebDAV connection was not saved', 'error');
  } finally {
    _setWebdavMutationPending(false);
  }
}

async function disconnectWebdavBackup() {
  if (_webdavMutationPending) return;
  if (!await _dlgConfirm('disconnect WebDAV backup? remote backups will stay on the server.')) return;
  if (_webdavMutationPending) return;
  const revision = _webdavDraftRevision;
  _setWebdavMutationPending(true);
  _setWebdavStatus('disconnecting…');
  try {
    const response = await _fetchWithRecentOwner('/api/backup/webdav', { method: 'DELETE' });
    const data = await _webdavResponseJson(response);
    if (!response.ok) throw new Error(_webdavError(data, 'WebDAV could not be disconnected'));
    _webdavLoadGeneration += 1;
    _webdavListGeneration += 1;
    if (revision === _webdavDraftRevision) _webdavDirty = false;
    _applyWebdavConfig(normalizeWebdavBackupConfig({}), true);
    _setWebdavStatus(_webdavDirty ? 'unsaved connection changes kept here' : 'not connected');
    toast('WebDAV disconnected', 'success');
  } catch (error) {
    _setWebdavStatus(error.message || 'WebDAV could not be disconnected', 'error');
    toast(error.message || 'WebDAV could not be disconnected', 'error');
  } finally {
    _setWebdavMutationPending(false);
  }
}

async function runWebdavBackup() {
  if (_webdavMutationPending || !_webdavConfigured) return;
  _setWebdavMutationPending(true);
  const button = document.getElementById('webdav-backup-run-btn');
  if (button) button.textContent = 'backing up…';
  _setWebdavStatus('creating and uploading encrypted backup…');
  try {
    const response = await _fetchWithRecentOwner('/api/backup/webdav/run', { method: 'POST' });
    const data = await _webdavResponseJson(response);
    if (!response.ok) throw new Error(_webdavError(data, 'WebDAV backup failed'));
    const lastSuccess = document.getElementById('webdav-backup-last-success');
    if (lastSuccess) lastSuccess.textContent = _formatWebdavTime(data.last_backup_at);
    const lastVerified = document.getElementById('webdav-backup-last-verified');
    if (lastVerified) lastVerified.textContent = _formatWebdavTime(data.last_verified_at);
    const warning = String(data.status_warning || '');
    toast(warning || 'WebDAV backup complete', warning ? '' : 'success', warning ? 6000 : 3000);
    const isCurrent = _webdavDeferredListLoad || (() => true);
    _webdavDeferredListLoad = null;
    await loadWebdavBackups(false, isCurrent);
    _setWebdavStatus(warning || 'backup uploaded and verified', warning ? '' : 'success');
  } catch (error) {
    _setWebdavStatus(error.message || 'WebDAV backup failed', 'error');
    toast(error.message || 'WebDAV backup failed', 'error');
  } finally {
    _setWebdavMutationPending(false);
  }
}

async function loadWebdavBackups(announce = false, isCurrent = () => true) {
  const generation = ++_webdavListGeneration;
  const refresh = document.getElementById('webdav-backup-refresh-btn');
  const selection = document.getElementById('webdav-backup-selection');
  if (!_webdavConfigured) {
    renderWebdavBackups([]);
    return;
  }
  if (refresh) { refresh.disabled = true; refresh.textContent = 'refreshing…'; }
  if (selection) selection.textContent = 'loading remote backups…';
  try {
    const response = await fetch('/api/backup/webdav/backups');
    const data = await _webdavResponseJson(response);
    if (!response.ok) throw new Error(_webdavError(data, 'could not load remote backups'));
    if (generation !== _webdavListGeneration || !isCurrent()) return;
    renderWebdavBackups(webdavBackupsFromResponse(data));
    if (announce) toast('remote backups refreshed', 'success');
  } catch (error) {
    if (generation !== _webdavListGeneration || !isCurrent()) return;
    renderWebdavBackups([]);
    if (selection) selection.textContent = error.message || 'could not load remote backups';
    if (announce) toast(error.message || 'could not load remote backups', 'error');
  } finally {
    if (generation === _webdavListGeneration && refresh) { refresh.disabled = _webdavMutationPending || !_webdavConfigured; refresh.textContent = 'refresh backups'; }
  }
}

function renderWebdavBackups(backups) {
  _webdavBackups = backups;
  const select = document.getElementById('webdav-backup-list');
  if (!select) return;
  const previous = select.value;
  if (!backups.length) {
    populateDropdown(select, [{ value: '', label: 'no remote backups found' }], '');
    select.disabled = true;
  } else {
    populateDropdown(select, backups.map(backup => ({ value: backup.filename, label: backup.filename })),
      backups.some(backup => backup.filename === previous) ? previous : backups[0].filename);
    select.disabled = false;
  }
  renderWebdavSelection();
}

function renderWebdavSelection() {
  const select = document.getElementById('webdav-backup-list');
  const selected = _webdavBackups.find(backup => backup.filename === select?.value);
  const label = document.getElementById('webdav-backup-selection');
  _setWebdavMutationPending(_webdavMutationPending);
  if (!label) return;
  if (!selected) {
    label.textContent = _webdavConfigured ? 'no remote backups yet.' : 'connect WebDAV to list backups.';
    return;
  }
  const details = [selected.filename];
  const size = _formatWebdavBytes(selected.bytes);
  if (size) details.push(size);
  if (selected.modified_at) details.push(_formatWebdavTime(selected.modified_at));
  label.textContent = details.join(' · ');
}

async function restoreWebdavBackup() {
  if (_webdavMutationPending || !_webdavConfigured) return;
  const select = document.getElementById('webdav-backup-list');
  const filename = select?.value || '';
  if (!filename) return;
  const keyInput = document.getElementById('webdav-backup-recovery-key');
  const keyFile = keyInput?.files[0];
  const status = document.getElementById('webdav-backup-restore-status');
  const button = document.getElementById('webdav-backup-restore-btn');
  const form = new FormData();
  form.append('filename', filename);
  if (keyFile) form.append('recovery_key', keyFile, keyFile.name);
  _setWebdavMutationPending(true);
  if (status) { status.hidden = false; status.textContent = 'downloading, verifying, and staging…'; }
  if (button) { button.disabled = true; button.textContent = 'staging…'; }
  try {
    const response = await _fetchWithRecentOwner('/api/backup/webdav/restore', { method: 'POST', body: form });
    const data = await _webdavResponseJson(response);
    if (!response.ok) throw new Error(_webdavError(data, 'remote backup could not be staged'));
    if (data?.status !== 'staged' || typeof data?.restore_id !== 'string' || !/^[0-9a-f]{32}$/.test(data.restore_id)) {
      throw new Error('could not verify the backup response');
    }
    const command = `alles restore apply ${data.restore_id}`;
    if (status) status.textContent = `verified and staged. live data is unchanged. stop Alles, then run: ${command}`;
    toast('remote backup verified and staged', 'success');
  } catch (error) {
    if (status) status.textContent = error.message || 'remote backup could not be staged';
    toast(error.message || 'remote backup could not be staged', 'error');
  } finally {
    _setWebdavMutationPending(false);
    if (keyInput) keyInput.value = '';
    const keyName = document.getElementById('webdav-backup-recovery-key-name');
    if (keyName) keyName.textContent = 'no separate key selected';
  }
}

// ── s3 backup ────────────────────────────────────────────────────────────────
let _s3Configured = false;
let _s3CredentialsSet = false;
let _s3Backups = [];
let _s3LoadGeneration = 0;
let _s3ListGeneration = 0;
let _s3DraftRevision = 0;
let _s3Dirty = false;
let _s3MutationPending = false;
let _s3DeferredListLoad = null;
let _setupLoadGeneration = 0;

export function normalizeS3BackupConfig(payload = {}) {
  const value = payload && typeof payload.s3 === 'object' ? payload.s3 : payload;
  return {
    configured: value?.configured === true,
    endpoint: String(value?.endpoint || ''),
    region: String(value?.region || ''),
    bucket: String(value?.bucket || ''),
    prefix: String(value?.prefix || ''),
    addressing_style: value?.addressing_style === 'virtual' ? 'virtual' : 'path',
    credentials_set: value?.credentials_set === true,
    last_backup_at: String(value?.last_backup_at || ''),
    last_verified_at: String(value?.last_verified_at || ''),
    last_filename: String(value?.last_filename || ''),
    last_bytes: Number.isFinite(Number(value?.last_bytes)) ? Number(value.last_bytes) : null,
    error: String(value?.error || ''),
  };
}

export function s3BackupConfigPayload(
  endpoint,
  region,
  bucket,
  prefix,
  addressingStyle,
  accessKeyId,
  secretAccessKey,
  hasSavedCredentials = false,
) {
  const endpointValue = String(endpoint || '').trim();
  const regionValue = String(region || '').trim();
  const bucketValue = String(bucket || '').trim();
  const prefixValue = String(prefix || '').trim();
  const styleValue = String(addressingStyle || 'path');
  const accessKeyValue = String(accessKeyId || '');
  const secretValue = String(secretAccessKey || '');
  if (!endpointValue) throw new Error('add the S3 https endpoint');
  let parsed;
  try { parsed = new URL(endpointValue); } catch { throw new Error('enter a valid S3 endpoint'); }
  if (parsed.protocol !== 'https:') throw new Error('the S3 endpoint must use https');
  if (parsed.username || parsed.password) throw new Error('keep S3 credentials out of the endpoint');
  if (parsed.search || parsed.hash) throw new Error('the S3 endpoint cannot include a query or fragment');
  if (!regionValue) throw new Error('add the S3 region');
  if (!bucketValue) throw new Error('add the existing S3 bucket');
  if (!['path', 'virtual'].includes(styleValue)) throw new Error('choose path or virtual addressing');
  if (!!accessKeyValue !== !!secretValue) throw new Error('enter both S3 credentials together');
  if (!accessKeyValue && !hasSavedCredentials) throw new Error('add the S3 credential pair');
  const result = {
    endpoint: parsed.toString(),
    region: regionValue,
    bucket: bucketValue,
    prefix: prefixValue,
    addressing_style: styleValue,
  };
  if (accessKeyValue && secretValue) {
    result.access_key_id = accessKeyValue;
    result.secret_access_key = secretValue;
  }
  return result;
}

export function s3BackupsFromResponse(payload = {}) {
  const values = Array.isArray(payload) ? payload : payload?.backups;
  if (!Array.isArray(values)) return [];
  return values.map(value => {
    if (typeof value === 'string') return { filename: value, bytes: null, modified_at: '' };
    const bytes = Number(value?.bytes);
    return {
      filename: String(value?.filename || ''),
      bytes: Number.isFinite(bytes) && bytes >= 0 ? bytes : null,
      modified_at: String(value?.modified_at || value?.last_modified || ''),
    };
  }).filter(value => value.filename).sort((left, right) => {
    const leftTime = Date.parse(left.modified_at);
    const rightTime = Date.parse(right.modified_at);
    if (!Number.isFinite(leftTime) || !Number.isFinite(rightTime)) return 0;
    return rightTime - leftTime;
  });
}

function _formatS3Time(value) {
  if (!value) return 'never';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'unknown' : formatDateTime(date);
}

function _formatS3Bytes(value) {
  if (!Number.isFinite(value) || value < 0) return '';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

async function _s3ResponseJson(response) {
  return response.json().catch(() => ({}));
}

function _s3Error(data, fallback, secrets = []) {
  let message = typeof data?.detail === 'string' && data.detail.trim() ? data.detail.trim() : fallback;
  for (const secret of secrets) {
    if (secret) message = message.split(secret).join('[hidden]');
  }
  return message;
}

function _setS3Status(message, kind = '') {
  const status = document.getElementById('s3-backup-status');
  if (!status) return;
  status.textContent = message;
  status.style.color = kind === 'error' ? 'var(--error)' : (kind === 'success' ? 'var(--green)' : 'var(--muted)');
}

function _setS3MutationPending(pending) {
  const wasPending = _s3MutationPending;
  if (pending && !_s3MutationPending) _s3LoadGeneration += 1;
  _s3MutationPending = pending;
  const save = document.getElementById('s3-backup-save-btn');
  if (save) {
    save.disabled = pending;
    if (!pending) save.textContent = _s3Configured ? 'save connection' : 'connect and save';
  }
  const disconnect = document.getElementById('s3-backup-disconnect-btn');
  if (disconnect) disconnect.disabled = pending || disconnect.hidden;
  const run = document.getElementById('s3-backup-run-btn');
  if (run) {
    run.disabled = pending || !_s3Configured;
    if (!pending) run.textContent = 'back up now';
  }
  const select = document.getElementById('s3-backup-list');
  if (select) select.disabled = pending || !_s3Configured || !_s3Backups.length;
  const restore = document.getElementById('s3-backup-restore-btn');
  if (restore) {
    restore.disabled = pending || !_s3Configured || !_s3Backups.some(backup => backup.filename === select?.value);
    if (!pending) restore.textContent = 'verify and stage selected restore';
  }
  const refresh = document.getElementById('s3-backup-refresh-btn');
  if (refresh) refresh.disabled = pending || !_s3Configured;
  for (const id of ['s3-backup-recovery-key-btn', 's3-backup-recovery-key']) {
    const control = document.getElementById(id);
    if (control) control.disabled = pending;
  }
  if (wasPending && !pending) {
    const isCurrent = _s3DeferredListLoad;
    _s3DeferredListLoad = null;
    if (_s3Configured && isCurrent?.()) loadS3Backups(false, isCurrent);
  }
}

function _applyS3Config(config, keepDraft = false) {
  const updateFields = !keepDraft || !_s3Dirty;
  _s3Configured = config.configured;
  _s3CredentialsSet = config.credentials_set;
  const endpoint = document.getElementById('s3-backup-endpoint');
  const region = document.getElementById('s3-backup-region');
  const bucket = document.getElementById('s3-backup-bucket');
  const prefix = document.getElementById('s3-backup-prefix');
  const addressingStyle = document.getElementById('s3-backup-addressing-style');
  const accessKey = document.getElementById('s3-backup-access-key-id');
  const secretKey = document.getElementById('s3-backup-secret-access-key');
  if (endpoint && updateFields) endpoint.value = config.endpoint;
  if (region && updateFields) region.value = config.region;
  if (bucket && updateFields) bucket.value = config.bucket;
  if (prefix && updateFields) prefix.value = config.prefix;
  if (addressingStyle && updateFields) addressingStyle.value = config.addressing_style;
  if (accessKey && updateFields) accessKey.value = '';
  if (secretKey && updateFields) secretKey.value = '';
  const disconnect = document.getElementById('s3-backup-disconnect-btn');
  if (disconnect) {
    disconnect.hidden = !config.configured && !config.error;
    disconnect.textContent = config.error ? 'remove broken settings' : 'disconnect';
  }
  _setS3MutationPending(_s3MutationPending);
  const refresh = document.getElementById('s3-backup-refresh-btn');
  if (refresh) refresh.disabled = _s3MutationPending || !config.configured;
  const lastSuccess = document.getElementById('s3-backup-last-success');
  if (lastSuccess) lastSuccess.textContent = _formatS3Time(config.last_backup_at);
  const lastVerified = document.getElementById('s3-backup-last-verified');
  if (lastVerified) lastVerified.textContent = _formatS3Time(config.last_verified_at);
  if (!_s3MutationPending) {
    if (config.error) _setS3Status(config.error, 'error');
    else _setS3Status(updateFields ? (config.configured ? 'connected' : 'not connected') : 'unsaved connection changes kept here', updateFields && config.configured ? 'success' : '');
  }
  if (!config.configured) renderS3Backups([]);
}

async function loadS3Backup(isCurrent = () => true) {
  if (!document.getElementById('s3-backup-card')) return;
  if (_s3MutationPending) { _s3DeferredListLoad = isCurrent; return; }
  const generation = ++_s3LoadGeneration;
  _setS3Status('checking connection…');
  try {
    const response = await fetch('/api/backup/s3');
    const data = await _s3ResponseJson(response);
    if (!response.ok) throw new Error(_s3Error(data, 'could not check S3'));
    if (generation !== _s3LoadGeneration || !isCurrent()) return;
    const config = normalizeS3BackupConfig(data);
    _applyS3Config(config, true);
    if (config.configured) await loadS3Backups(false, isCurrent);
  } catch (error) {
    if (generation !== _s3LoadGeneration || !isCurrent()) return;
    _s3Configured = false;
    _s3CredentialsSet = false;
    _setS3Status(error.message || 'could not check S3', 'error');
    renderS3Backups([]);
  }
}

async function saveS3Backup() {
  if (_s3MutationPending) return;
  const revision = _s3DraftRevision;
  _s3LoadGeneration += 1;
  const endpoint = document.getElementById('s3-backup-endpoint');
  const region = document.getElementById('s3-backup-region');
  const bucket = document.getElementById('s3-backup-bucket');
  const prefix = document.getElementById('s3-backup-prefix');
  const addressingStyle = document.getElementById('s3-backup-addressing-style');
  const accessKey = document.getElementById('s3-backup-access-key-id');
  const secretKey = document.getElementById('s3-backup-secret-access-key');
  const button = document.getElementById('s3-backup-save-btn');
  const accessKeyValue = accessKey?.value || '';
  const secretValue = secretKey?.value || '';
  let payload;
  try {
    payload = s3BackupConfigPayload(
      endpoint?.value,
      region?.value,
      bucket?.value,
      prefix?.value,
      addressingStyle?.value,
      accessKeyValue,
      secretValue,
      _s3CredentialsSet,
    );
  } catch (error) {
    _setS3Status(error.message, 'error');
    toast(error.message, 'error');
    return;
  }
  if (accessKey) accessKey.value = '';
  if (secretKey) secretKey.value = '';
  _setS3MutationPending(true);
  if (button) button.textContent = 'checking…';
  _setS3Status('creating and removing a probe object…');
  try {
    const response = await _fetchWithRecentOwner('/api/backup/s3', {
      method: 'PUT',
      headers: {'content-type':'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await _s3ResponseJson(response);
    if (!response.ok) throw new Error(_s3Error(data, 'S3 connection was not saved', [accessKeyValue, secretValue]));
    const config = normalizeS3BackupConfig(data);
    if (revision === _s3DraftRevision) _s3Dirty = false;
    _applyS3Config(config, true);
    toast('S3 connection saved', 'success');
    const isCurrent = _s3DeferredListLoad || (() => true);
    _s3DeferredListLoad = null;
    await loadS3Backups(false, isCurrent);
    _setS3Status(_s3Dirty ? 'saved; newer connection edits kept here' : 'connected and saved', 'success');
  } catch (error) {
    _setS3Status(error.message || 'S3 connection was not saved', 'error');
    toast(error.message || 'S3 connection was not saved', 'error');
  } finally {
    _setS3MutationPending(false);
  }
}

async function disconnectS3Backup() {
  if (_s3MutationPending) return;
  if (!await _dlgConfirm('disconnect S3 backup? remote backups will stay in the bucket.')) return;
  if (_s3MutationPending) return;
  const revision = _s3DraftRevision;
  _setS3MutationPending(true);
  _setS3Status('disconnecting…');
  try {
    const response = await _fetchWithRecentOwner('/api/backup/s3', { method: 'DELETE' });
    const data = await _s3ResponseJson(response);
    if (!response.ok) throw new Error(_s3Error(data, 'S3 could not be disconnected'));
    _s3LoadGeneration += 1;
    _s3ListGeneration += 1;
    if (revision === _s3DraftRevision) _s3Dirty = false;
    _applyS3Config(normalizeS3BackupConfig({}), true);
    _setS3Status(_s3Dirty ? 'unsaved connection changes kept here' : 'not connected');
    toast('S3 disconnected', 'success');
  } catch (error) {
    _setS3Status(error.message || 'S3 could not be disconnected', 'error');
    toast(error.message || 'S3 could not be disconnected', 'error');
  } finally {
    _setS3MutationPending(false);
  }
}

async function runS3Backup() {
  if (_s3MutationPending || !_s3Configured) return;
  _setS3MutationPending(true);
  const button = document.getElementById('s3-backup-run-btn');
  if (button) button.textContent = 'backing up…';
  _setS3Status('creating and copying encrypted backup…');
  try {
    const response = await _fetchWithRecentOwner('/api/backup/s3/run', { method: 'POST' });
    const data = await _s3ResponseJson(response);
    if (!response.ok) throw new Error(_s3Error(data, 'S3 backup failed'));
    const lastSuccess = document.getElementById('s3-backup-last-success');
    if (lastSuccess) lastSuccess.textContent = _formatS3Time(data.last_backup_at);
    const lastVerified = document.getElementById('s3-backup-last-verified');
    if (lastVerified) {
      lastVerified.textContent = _formatS3Time(data.last_verified_at || data.completed_at || data.last_backup_at);
    }
    const warning = String(data.status_warning || '');
    toast(warning || 'S3 backup complete', warning ? '' : 'success', warning ? 6000 : 3000);
    const isCurrent = _s3DeferredListLoad || (() => true);
    _s3DeferredListLoad = null;
    await loadS3Backups(false, isCurrent);
    _setS3Status(warning || 'backup copied and verified by read-back', warning ? '' : 'success');
  } catch (error) {
    _setS3Status(error.message || 'S3 backup failed', 'error');
    toast(error.message || 'S3 backup failed', 'error');
  } finally {
    _setS3MutationPending(false);
  }
}

async function loadS3Backups(announce = false, isCurrent = () => true) {
  const generation = ++_s3ListGeneration;
  const refresh = document.getElementById('s3-backup-refresh-btn');
  const selection = document.getElementById('s3-backup-selection');
  if (!_s3Configured) {
    renderS3Backups([]);
    return;
  }
  if (refresh) { refresh.disabled = true; refresh.textContent = 'refreshing…'; }
  if (selection) selection.textContent = 'loading remote backups…';
  try {
    const response = await fetch('/api/backup/s3/backups');
    const data = await _s3ResponseJson(response);
    if (!response.ok) throw new Error(_s3Error(data, 'could not load remote backups'));
    if (generation !== _s3ListGeneration || !isCurrent()) return;
    renderS3Backups(s3BackupsFromResponse(data));
    if (announce) toast('remote backups refreshed', 'success');
  } catch (error) {
    if (generation !== _s3ListGeneration || !isCurrent()) return;
    renderS3Backups([]);
    if (selection) selection.textContent = error.message || 'could not load remote backups';
    if (announce) toast(error.message || 'could not load remote backups', 'error');
  } finally {
    if (generation === _s3ListGeneration && refresh) { refresh.disabled = _s3MutationPending || !_s3Configured; refresh.textContent = 'refresh backups'; }
  }
}

function renderS3Backups(backups) {
  _s3Backups = backups;
  const select = document.getElementById('s3-backup-list');
  if (!select) return;
  const previous = select.value;
  if (!backups.length) {
    populateDropdown(select, [{ value: '', label: 'no remote backups found' }], '');
    select.disabled = true;
  } else {
    populateDropdown(select, backups.map(backup => ({ value: backup.filename, label: backup.filename })),
      backups.some(backup => backup.filename === previous) ? previous : backups[0].filename);
    select.disabled = false;
  }
  renderS3Selection();
}

function renderS3Selection() {
  const select = document.getElementById('s3-backup-list');
  const selected = _s3Backups.find(backup => backup.filename === select?.value);
  const label = document.getElementById('s3-backup-selection');
  _setS3MutationPending(_s3MutationPending);
  if (!label) return;
  if (!selected) {
    label.textContent = _s3Configured ? 'no remote backups yet.' : 'connect S3 to list backups.';
    return;
  }
  const details = [selected.filename];
  const size = _formatS3Bytes(selected.bytes);
  if (size) details.push(size);
  if (selected.modified_at) details.push(_formatS3Time(selected.modified_at));
  label.textContent = details.join(' · ');
}

async function restoreS3Backup() {
  if (_s3MutationPending || !_s3Configured) return;
  const select = document.getElementById('s3-backup-list');
  const filename = select?.value || '';
  if (!filename) return;
  const keyInput = document.getElementById('s3-backup-recovery-key');
  const keyFile = keyInput?.files[0];
  const status = document.getElementById('s3-backup-restore-status');
  const button = document.getElementById('s3-backup-restore-btn');
  const form = new FormData();
  form.append('filename', filename);
  if (keyFile) form.append('recovery_key', keyFile, keyFile.name);
  _setS3MutationPending(true);
  if (status) { status.hidden = false; status.textContent = 'downloading, verifying, and staging…'; }
  if (button) { button.disabled = true; button.textContent = 'staging…'; }
  try {
    const response = await _fetchWithRecentOwner('/api/backup/s3/restore', { method: 'POST', body: form });
    const data = await _s3ResponseJson(response);
    if (!response.ok) throw new Error(_s3Error(data, 'remote backup could not be staged'));
    if (data?.status !== 'staged' || typeof data?.restore_id !== 'string' || !/^[0-9a-f]{32}$/.test(data.restore_id)) {
      throw new Error('could not verify the backup response');
    }
    const command = `alles restore apply ${data.restore_id}`;
    if (status) status.textContent = `verified and staged. live data is unchanged. stop Alles, then run: ${command}`;
    toast('remote backup verified and staged', 'success');
  } catch (error) {
    if (status) status.textContent = error.message || 'remote backup could not be staged';
    toast(error.message || 'remote backup could not be staged', 'error');
  } finally {
    _setS3MutationPending(false);
    if (keyInput) keyInput.value = '';
    const keyName = document.getElementById('s3-backup-recovery-key-name');
    if (keyName) keyName.textContent = 'no separate key selected';
  }
}

async function loadSetupStatus(isCurrent) {
  const status = document.getElementById('setup-resume-status');
  const button = document.getElementById('setup-resume-btn');
  if (!status || !button) return;
  const generation = ++_setupLoadGeneration;
  try {
    const data = await fetch('/api/setup/status').then(response => {
      if (!response.ok) throw new Error();
      return response.json();
    });
    if (generation !== _setupLoadGeneration || !isCurrent()) return;
    const setup = data.setup || {};
    status.textContent = setup.completed
      ? 'setup is complete. open it to review the saved summary.'
      : setup.dismissed
        ? 'setup is paused. your saved steps are still here.'
        : `setup is in progress at ${String(setup.next_step || 'basics').replace('_', ' + ')}.`;
    button.textContent = setup.completed ? 'review setup' : 'resume setup';
  } catch {
    if (generation !== _setupLoadGeneration || !isCurrent()) return;
    status.textContent = 'setup status could not be loaded.';
  }
}


function _wireBackupsPane(closeSettings) {
  for (const type of ['input', 'change']) {
    document.getElementById('webdav-backup-card')?.addEventListener(type, event => {
      if (!['webdav-backup-url', 'webdav-backup-username', 'webdav-backup-password'].includes(event.target.id)) return;
      _webdavDirty = true;
      _webdavDraftRevision += 1;
      if (!_webdavMutationPending) _setWebdavStatus('connection changes not saved');
    });
    document.getElementById('s3-backup-card')?.addEventListener(type, event => {
      if (!['s3-backup-endpoint', 's3-backup-region', 's3-backup-bucket', 's3-backup-prefix',
        's3-backup-addressing-style', 's3-backup-access-key-id', 's3-backup-secret-access-key'].includes(event.target.id)) return;
      _s3Dirty = true;
      _s3DraftRevision += 1;
      if (!_s3MutationPending) _setS3Status('connection changes not saved');
    });
  }

  // ── backup ──
  document.getElementById('setup-resume-btn')?.addEventListener('click', () => {
    closeSettings();
    window._openSetupWizard?.({ resume: true });
  });
  document.getElementById('backup-export-btn')?.addEventListener('click', async () => {
    if (await _confirmRecentOwner()) window.location = '/api/backup';
  });
  document.getElementById('backup-key-export-btn')?.addEventListener('click', async () => {
    if (await _confirmRecentOwner()) window.location = '/api/backup/recovery-key';
  });
  const restoreInput = document.getElementById('backup-restore-input');
  const restoreButton = document.getElementById('backup-restore-btn');
  const keyInput = document.getElementById('backup-recovery-key-input');
  const keyButton = document.getElementById('backup-recovery-key-btn');
  let checkingBackup = false;
  restoreButton?.addEventListener('click', () => restoreInput?.click());
  keyButton?.addEventListener('click', () => keyInput?.click());
  document.getElementById('backup-recovery-key-input')?.addEventListener('change', e => {
    const name = document.getElementById('backup-recovery-key-name');
    if (name) name.textContent = e.target.files[0]?.name || 'no separate key selected';
  });
  restoreInput?.addEventListener('change', async () => {
    const file = restoreInput.files[0];
    if (!file || checkingBackup) return;
    checkingBackup = true;
    const returnFocus = document.activeElement === restoreButton;
    const controls = [restoreButton, restoreInput, keyButton, keyInput].filter(Boolean);
    controls.forEach(control => { control.disabled = true; });
    restoreButton?.setAttribute('aria-busy', 'true');
    const status = document.getElementById('backup-restore-status');
    const showStatus = text => {
      if (status) { status.hidden = false; status.textContent = text; }
    };
    showStatus('checking backup…');
    const fd = new FormData(); fd.append('file', file);
    if (keyInput?.files[0]) fd.append('recovery_key', keyInput.files[0]);
    const send = async () => {
      const response = await fetch('/api/backup/restore', { method: 'POST', body: fd });
      let data;
      try { data = await response.json(); }
      catch { throw new Error('could not read the backup response'); }
      return { response, data };
    };
    try {
      let { response, data } = await send();
      if (response.status === 403 && data?.code === 'recent_auth_required') {
        showStatus('confirm your Alles password to check this backup.');
        if (!await _confirmRecentOwner()) {
          showStatus('backup check canceled: password confirmation was not completed. choose a backup file to try again.');
          return;
        }
        showStatus('checking backup…');
        ({ response, data } = await send());
      }
      if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'backup check failed');
      if (data?.status !== 'staged' || !/^[0-9a-f]{32}$/.test(data?.restore_id || '')) {
        throw new Error('could not verify the backup response');
      }
      const command = data.apply_command || `alles restore apply ${data.restore_id}`;
      showStatus(`verified and staged. live data is unchanged. stop Alles, then run: ${command}`);
      toast('backup verified and staged', 'success');
    } catch (error) {
      const message = error instanceof TypeError ? 'connection lost while checking the backup' : error.message || 'backup check failed';
      showStatus(`${message}. choose a backup file to try again.`);
      toast(message, 'error');
    } finally {
      restoreInput.value = '';
      if (keyInput) keyInput.value = '';
      const keyName = document.getElementById('backup-recovery-key-name');
      if (keyName) keyName.textContent = 'no separate key selected';
      checkingBackup = false;
      controls.forEach(control => { control.disabled = false; });
      restoreButton?.removeAttribute('aria-busy');
      if (returnFocus && document.activeElement === document.body && restoreButton?.offsetParent) restoreButton.focus();
    }
  });
  document.getElementById('webdav-backup-save-btn')?.addEventListener('click', saveWebdavBackup);
  document.getElementById('webdav-backup-disconnect-btn')?.addEventListener('click', disconnectWebdavBackup);
  document.getElementById('webdav-backup-run-btn')?.addEventListener('click', runWebdavBackup);
  document.getElementById('webdav-backup-refresh-btn')?.addEventListener('click', () => loadWebdavBackups(true));
  document.getElementById('webdav-backup-list')?.addEventListener('change', renderWebdavSelection);
  document.getElementById('webdav-backup-recovery-key-btn')?.addEventListener('click', () => {
    document.getElementById('webdav-backup-recovery-key')?.click();
  });
  document.getElementById('webdav-backup-recovery-key')?.addEventListener('change', event => {
    const label = document.getElementById('webdav-backup-recovery-key-name');
    if (label) label.textContent = event.target.files[0]?.name || 'no separate key selected';
  });
  document.getElementById('webdav-backup-restore-btn')?.addEventListener('click', restoreWebdavBackup);
  document.getElementById('s3-backup-save-btn')?.addEventListener('click', saveS3Backup);
  document.getElementById('s3-backup-disconnect-btn')?.addEventListener('click', disconnectS3Backup);
  document.getElementById('s3-backup-run-btn')?.addEventListener('click', runS3Backup);
  document.getElementById('s3-backup-refresh-btn')?.addEventListener('click', () => loadS3Backups(true));
  document.getElementById('s3-backup-list')?.addEventListener('change', renderS3Selection);
  document.getElementById('s3-backup-recovery-key-btn')?.addEventListener('click', () => {
    document.getElementById('s3-backup-recovery-key')?.click();
  });
  document.getElementById('s3-backup-recovery-key')?.addEventListener('change', event => {
    const label = document.getElementById('s3-backup-recovery-key-name');
    if (label) label.textContent = event.target.files[0]?.name || 'no separate key selected';
  });
  document.getElementById('s3-backup-restore-btn')?.addEventListener('click', restoreS3Backup);

}

export function createBackupPane(closeSettings) {
  return createSettingsPane({
    init: () => _wireBackupsPane(closeSettings),
    load: isCurrent => Promise.all([
      loadSetupStatus(isCurrent), loadWebdavBackup(isCurrent), loadS3Backup(isCurrent),
    ]),
    dispose() {
      _setupLoadGeneration += 1;
      _webdavLoadGeneration += 1;
      _webdavListGeneration += 1;
      _s3LoadGeneration += 1;
      _s3ListGeneration += 1;
      for (const kind of ['webdav', 's3']) {
        const refresh = document.getElementById(`${kind}-backup-refresh-btn`);
        if (refresh) {
          refresh.disabled = kind === 'webdav' ? _webdavMutationPending || !_webdavConfigured : _s3MutationPending || !_s3Configured;
          refresh.textContent = 'refresh backups';
        }
      }
    },
  });
}

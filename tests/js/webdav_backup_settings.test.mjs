import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

globalThis.window = {};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.document = {};
globalThis.HTMLInputElement = class {
  get value() { return ''; }
  set value(_value) {}
};

const {
  normalizeWebdavBackupConfig,
  webdavBackupConfigPayload,
  webdavBackupsFromResponse,
} = await import('../../static/js/settings.js');

const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const source = readFileSync(new URL('../../static/js/settings.js', import.meta.url), 'utf8');

test('webdav connection payload requires https and never resends a blank saved password', () => {
  assert.throws(
    () => webdavBackupConfigPayload('http://dav.example.test/alles', 'jx', 'secret'),
    /must use https/,
  );
  assert.throws(
    () => webdavBackupConfigPayload('https://jx:secret@dav.example.test/alles', 'jx', 'secret'),
    /out of the url/,
  );
  assert.throws(
    () => webdavBackupConfigPayload('https://dav.example.test/alles', 'jx', ''),
    /password/,
  );
  assert.deepEqual(
    webdavBackupConfigPayload('https://dav.example.test/alles', 'jx', '', true),
    { url: 'https://dav.example.test/alles', username: 'jx' },
  );
});

test('webdav config normalization keeps password fields out of ui state', () => {
  const config = normalizeWebdavBackupConfig({
    configured: true,
    url: 'https://dav.example.test/alles',
    username: 'jx',
    password: 'must-not-render',
    last_backup_at: '2026-07-12T02:00:00Z',
    last_verified_at: '2026-07-12T02:01:00Z',
    error: 'webdav backup configuration could not be loaded',
  });
  assert.equal(config.configured, true);
  assert.equal(config.url, 'https://dav.example.test/alles');
  assert.equal(config.username, 'jx');
  assert.equal(config.error, 'webdav backup configuration could not be loaded');
  assert.equal('password' in config, false);
});

test('webdav backup list drops invalid rows and puts the newest backup first', () => {
  const backups = webdavBackupsFromResponse({ backups: [
    { filename: 'older.alles-backup', bytes: 20, modified_at: '2026-07-11T02:00:00Z' },
    { filename: '', bytes: 50, modified_at: '2026-07-13T02:00:00Z' },
    { filename: 'newer.alles-backup', bytes: 40, modified_at: '2026-07-12T02:00:00Z' },
  ] });
  assert.deepEqual(backups.map(item => item.filename), [
    'newer.alles-backup',
    'older.alles-backup',
  ]);
});

test('webdav settings use hidden secret inputs and accessible status regions', () => {
  assert.match(html, /id="webdav-backup-password"[^>]*type="password"|type="password"[^>]*id="webdav-backup-password"/);
  assert.match(html, /id="webdav-backup-recovery-key"[^>]*type="file"|type="file"[^>]*id="webdav-backup-recovery-key"/);
  assert.match(html, /<button[^>]*id="webdav-backup-recovery-key-btn"/);
  assert.match(html, /id="webdav-backup-status"[^>]*aria-live="polite"/);
  assert.match(html, /id="webdav-backup-restore-status"[^>]*aria-live="polite"/);
  assert.doesNotMatch(html, /id="webdav-backup-password"[^>]*\svalue=/);
});

test('every webdav mutation uses recent-owner confirmation and restore sends multipart fields', () => {
  assert.equal(source.split("_fetchWithRecentOwner('/api/backup/webdav',").length - 1, 2);
  assert.equal(source.split("_fetchWithRecentOwner('/api/backup/webdav/run',").length - 1, 1);
  assert.equal(source.split("_fetchWithRecentOwner('/api/backup/webdav/restore',").length - 1, 1);
  assert.match(source, /form\.append\('filename', filename\)/);
  assert.match(source, /form\.append\('recovery_key', keyFile, keyFile\.name\)/);
  assert.match(source, /if \(config\.error\) _setWebdavStatus\(config\.error, 'error'\)/);
  assert.match(source, /config\.error \? 'remove broken settings' : 'disconnect'/);
  assert.match(source, /data\.status_warning/);
});

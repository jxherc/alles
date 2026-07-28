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
  _mergeHomeShortcutOrder,
  normalizeS3BackupConfig,
  s3BackupConfigPayload,
  s3BackupsFromResponse,
} = await import('../../static/js/settings.js');

const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const source = readFileSync(new URL('../../static/js/settings.js', import.meta.url), 'utf8');
const s3Start = source.indexOf('// ── s3 backup');
const s3Source = source.slice(s3Start, source.indexOf('// ── models pane', s3Start));

test('Home shortcut visibility preserves custom keys and surviving positions', () => {
  const original = ['custom-a', 'inbox', 'custom-b', 'files'];

  assert.deepEqual(_mergeHomeShortcutOrder(['files'], original), [
    'custom-a',
    'custom-b',
    'files',
  ]);
  assert.deepEqual(_mergeHomeShortcutOrder([], original), ['custom-a', 'custom-b']);
  assert.deepEqual(_mergeHomeShortcutOrder(['files', 'inbox'], original), [
    'custom-a',
    'files',
    'custom-b',
    'inbox',
  ]);
});

test('s3 connection payload requires https and a complete credential pair', () => {
  assert.throws(
    () => s3BackupConfigPayload('http://s3.example.test', 'us-east-1', 'backups', '', 'path', 'id', 'secret'),
    /must use https/,
  );
  assert.throws(
    () => s3BackupConfigPayload('https://id:secret@s3.example.test', 'us-east-1', 'backups', '', 'path', 'id', 'secret'),
    /out of the endpoint/,
  );
  assert.throws(
    () => s3BackupConfigPayload('https://s3.example.test', 'us-east-1', 'backups', '', 'path', 'id', ''),
    /both S3 credentials/,
  );
  assert.throws(
    () => s3BackupConfigPayload('https://s3.example.test', 'us-east-1', 'backups', '', 'path', '', ''),
    /credential pair/,
  );
});

test('blank s3 credentials reuse the sealed pair without sending credential fields', () => {
  assert.deepEqual(
    s3BackupConfigPayload(
      'https://s3.example.test',
      'us-east-1',
      'backups',
      'alles',
      'virtual',
      '',
      '',
      true,
    ),
    {
      endpoint: 'https://s3.example.test/',
      region: 'us-east-1',
      bucket: 'backups',
      prefix: 'alles',
      addressing_style: 'virtual',
    },
  );
});

test('s3 config normalization keeps credential values out of ui state', () => {
  const config = normalizeS3BackupConfig({
    configured: true,
    endpoint: 'https://s3.example.test',
    region: 'us-east-1',
    bucket: 'backups',
    prefix: 'alles',
    addressing_style: 'virtual',
    credentials_set: true,
    access_key_id: 'must-not-render',
    secret_access_key: 'must-not-render',
    last_backup_at: '2026-07-12T02:00:00Z',
    last_verified_at: '2026-07-12T02:01:00Z',
    error: 's3 backup configuration could not be loaded',
  });
  assert.equal(config.configured, true);
  assert.equal(config.endpoint, 'https://s3.example.test');
  assert.equal(config.credentials_set, true);
  assert.equal(config.error, 's3 backup configuration could not be loaded');
  assert.equal('access_key_id' in config, false);
  assert.equal('secret_access_key' in config, false);
});

test('s3 backup list drops invalid rows and puts the newest backup first', () => {
  const backups = s3BackupsFromResponse({ backups: [
    { filename: 'older.alles-backup', bytes: 20, modified_at: '2026-07-11T02:00:00Z' },
    { filename: '', bytes: 50, modified_at: '2026-07-13T02:00:00Z' },
    { filename: 'newer.alles-backup', bytes: 40, last_modified: '2026-07-12T02:00:00Z' },
  ] });
  assert.deepEqual(backups.map(item => item.filename), [
    'newer.alles-backup',
    'older.alles-backup',
  ]);
});

test('s3 settings hide secrets and explain backup limits and recovery needs', () => {
  assert.match(html, /id="s3-backup-access-key-id"[^>]*type="password"|type="password"[^>]*id="s3-backup-access-key-id"/);
  assert.match(html, /id="s3-backup-secret-access-key"[^>]*type="password"|type="password"[^>]*id="s3-backup-secret-access-key"/);
  assert.match(html, /id="s3-backup-recovery-key"[^>]*type="file"|type="file"[^>]*id="s3-backup-recovery-key"/);
  assert.match(html, /id="s3-backup-status"[^>]*aria-live="polite"/);
  assert.match(html, /id="s3-backup-restore-status"[^>]*aria-live="polite"/);
  assert.doesNotMatch(html, /id="s3-backup-(?:access-key-id|secret-access-key)"[^>]*\svalue=/);
  assert.match(html, /creates and removes tiny probe objects/i);
  assert.match(html, /backup-only/i);
  assert.match(html, /copy is not atomic/i);
  assert.match(html, /5 GB or smaller/i);
  assert.match(html, /keep your S3 credentials and recovery-key file somewhere outside Alles/i);
});

test('every s3 mutation uses recent-owner confirmation and restore sends multipart fields', () => {
  assert.equal(source.split("_fetchWithRecentOwner('/api/backup/s3',").length - 1, 2);
  assert.equal(source.split("_fetchWithRecentOwner('/api/backup/s3/run',").length - 1, 1);
  assert.equal(source.split("_fetchWithRecentOwner('/api/backup/s3/restore',").length - 1, 1);
  assert.match(s3Source, /form\.append\('filename', filename\)/);
  assert.match(s3Source, /form\.append\('recovery_key', keyFile, keyFile\.name\)/);
  assert.match(s3Source, /if \(accessKey\) accessKey\.value = ''/);
  assert.match(s3Source, /if \(secretKey\) secretKey\.value = ''/);
  assert.ok(
    s3Source.indexOf("if (accessKey) accessKey.value = ''") < s3Source.indexOf('payload = s3BackupConfigPayload('),
  );
  assert.ok(
    s3Source.indexOf("if (secretKey) secretKey.value = ''") < s3Source.indexOf('payload = s3BackupConfigPayload('),
  );
  assert.match(s3Source, /if \(config\.error\) _setS3Status\(config\.error, 'error'\)/);
  assert.match(s3Source, /config\.error \? 'remove broken settings' : 'disconnect'/);
  assert.match(s3Source, /data\.status_warning/);
  assert.doesNotMatch(s3Source, /\.innerHTML\s*=/);
});

test('opening the backup pane loads webdav and s3 independently', () => {
  assert.match(
    source,
    /if \(name === 'backup'\)\s+\{ loadSetupStatus\(\); loadWebdavBackup\(\); loadS3Backup\(\); \}/,
  );
});

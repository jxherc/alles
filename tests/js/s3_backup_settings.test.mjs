import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';
import { createSettingsPane } from '../../static/js/settings/pane.js';

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
const source = readFileSync(new URL('../../static/js/settings/backups.js', import.meta.url), 'utf8');
const s3Start = source.indexOf('// ── s3 backup');
const s3Source = source.slice(s3Start, source.indexOf('async function loadSetupStatus', s3Start));

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
  assert.match(s3Source, /if \(config\.error\) _setS3Status\(config\.error, 'error'\)/);
  assert.match(s3Source, /config\.error \? 'remove broken settings' : 'disconnect'/);
  assert.match(s3Source, /data\.status_warning/);
  assert.doesNotMatch(s3Source, /\.innerHTML\s*=/);
});

test('opening the backup pane loads webdav and s3 independently', () => {
  assert.match(
    source,
    /load: isCurrent => Promise\.all\(\[\s*loadSetupStatus\(isCurrent\), loadWebdavBackup\(isCurrent\), loadS3Backup\(isCurrent\)/,
  );
});

test('s3 local validation keeps credentials for a corrected-only retry and submitted failures clear them', async () => {
  const nodes = new Map();
  for (const name of ['endpoint', 'region', 'bucket', 'prefix', 'addressing-style', 'access-key-id', 'secret-access-key', 'status', 'save-btn']) {
    nodes.set(`s3-backup-${name}`, { value: '', disabled: false, textContent: '', style: {} });
  }
  const field = name => nodes.get(`s3-backup-${name}`);
  field('endpoint').value = 'https://s3.example.test';
  field('bucket').value = 'backups';
  field('prefix').value = 'alles';
  field('addressing-style').value = 'path';
  field('access-key-id').value = 'example-access-key-id';
  field('secret-access-key').value = 'example-secret-access-key';
  const requests = [];
  const notices = [];
  let release;
  const context = {
    document: { getElementById: id => nodes.get(id) },
    URL,
    toast: (message, kind) => notices.push({ message, kind }),
    _fetchWithRecentOwner: (url, options) => {
      assert.equal(field('access-key-id').value, '');
      assert.equal(field('secret-access-key').value, '');
      requests.push({ url, options });
      return new Promise(resolve => { release = resolve; });
    },
  };
  runInNewContext(`${s3Source.replace(/^export /gm, '')}\n_s3Dirty = true; globalThis.save = saveS3Backup;`, context);

  await context.save();
  assert.equal(requests.length, 0);
  assert.equal(field('access-key-id').value, 'example-access-key-id');
  assert.equal(field('secret-access-key').value, 'example-secret-access-key');
  assert.equal(field('status').textContent, 'add the S3 region');
  assert.equal(field('save-btn').disabled, false);

  field('region').value = 'us-east-1';
  const saving = context.save();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/backup/s3');
  assert.equal(requests[0].options.method, 'PUT');
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    endpoint: 'https://s3.example.test/', region: 'us-east-1', bucket: 'backups',
    prefix: 'alles', addressing_style: 'path',
    access_key_id: 'example-access-key-id', secret_access_key: 'example-secret-access-key',
  });
  assert.equal(field('save-btn').disabled, true);
  await context.save();
  assert.equal(requests.length, 1);
  release({ ok: false, json: async () => ({ detail: 'synthetic save refused' }) });
  await saving;
  assert.equal(field('save-btn').disabled, false);
  assert.equal(field('access-key-id').value, '');
  assert.equal(field('secret-access-key').value, '');
  assert.equal(field('status').textContent, 'synthetic save refused');
  assert.equal(notices.at(-1).kind, 'error');
});

test('s3 mutations reconcile reopening during the write or its list read', async t => {
  for (const action of ['save', 'run']) {
    for (const timing of ['mutation', 'list']) {
      await t.test(`${action}: reopened during ${timing}`, async () => {
        const nodes = new Map();
        for (const name of ['card', 'endpoint', 'region', 'bucket', 'prefix', 'addressing-style', 'access-key-id', 'secret-access-key', 'status', 'save-btn', 'disconnect-btn', 'run-btn', 'list', 'selection', 'restore-btn', 'refresh-btn']) {
          const id = `s3-backup-${name}`;
          nodes.set(id, {
            id, value: '', disabled: false, hidden: false, textContent: '', style: {},
            listeners: {}, addEventListener(type, listener) { this.listeners[type] = listener; },
          });
        }
        const field = name => nodes.get(`s3-backup-${name}`);
        const config = {
          configured: true, credentials_set: true, endpoint: 'https://s3.example.test/',
          region: 'us-east-1', bucket: 'backups', prefix: '', addressing_style: 'path',
        };
        const currentFile = `${action}-current.enc`;
        const writes = [];
        let configReads = 0;
        let listReads = 0;
        let postWrite = false;
        let releaseMutation;
        let releaseList;
        let firstListStarted;
        const firstList = new Promise(resolve => { firstListStarted = resolve; });
        const response = data => ({ ok: true, json: async () => data });
        const context = {
          document: { getElementById: id => nodes.get(id) }, URL, createSettingsPane,
          toast() {}, formatDateTime: () => 'synthetic time',
          populateDropdown: (node, _options, value) => { node.value = value; },
          _fetchWithRecentOwner: (url, options) => {
            writes.push({ url, method: options.method });
            return new Promise(resolve => { releaseMutation = resolve; });
          },
          fetch: async url => {
            if (url === '/api/backup/s3') { configReads += 1; return response(config); }
            assert.equal(url, '/api/backup/s3/backups');
            if (!postWrite) return response({ backups: ['before.enc'] });
            listReads += 1;
            if (timing === 'list' && listReads === 1) {
              firstListStarted();
              return new Promise(resolve => { releaseList = resolve; });
            }
            if (timing === 'mutation' && listReads > 1) {
              return { ok: false, json: async () => ({ detail: 'unexpected second list rejected' }) };
            }
            return response({ backups: [currentFile] });
          },
        };
        runInNewContext(`${source.replace(/^import .*;\n/gm, '').replace(/^export /gm, '')}\nglobalThis.pane = createBackupPane(() => {}); globalThis.mutate = ${action === 'save' ? 'saveS3Backup' : 'runS3Backup'};`, context);
        await context.pane.load();
        const running = context.mutate();
        assert.equal(writes.length, 1);
        assert.equal(writes[0].method, action === 'save' ? 'PUT' : 'POST');
        assert.equal(field(`${action}-btn`).disabled, true);
        await context.mutate();
        assert.equal(writes.length, 1);
        if (timing === 'list') {
          postWrite = true;
          releaseMutation(response(config));
          await firstList;
        }
        context.pane.dispose();
        await context.pane.load();
        field('bucket').value = 'newer-draft';
        field('card').listeners.input({ target: field('bucket') });
        assert.equal(field(`${action}-btn`).disabled, true);
        assert.equal(configReads, 1);
        if (timing === 'mutation') {
          assert.equal(listReads, 0);
          postWrite = true;
          releaseMutation(response(config));
        } else {
          releaseList(response({ backups: ['stale.enc'] }));
        }
        await running;
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(listReads, timing === 'mutation' ? 1 : 2);
        assert.equal(field('list').value, currentFile);
        assert.match(field('selection').textContent, new RegExp(currentFile));
        assert.equal(field('bucket').value, 'newer-draft');
        assert.equal(field('status').textContent, action === 'save' ? 'saved; newer connection edits kept here' : 'backup copied and verified by read-back');
        assert.equal(field('restore-btn').disabled, false);
        assert.equal(field('refresh-btn').disabled, false);
        assert.equal(configReads, 1);
      });
    }
  }
});

test('s3 restores require a staged receipt and derive its command from the validated id', async () => {
  const nodes = new Map();
  const keyFile = { name: 'synthetic-recovery.key' };
  for (const name of ['list', 'restore-status', 'restore-btn', 'save-btn', 'disconnect-btn', 'run-btn', 'refresh-btn', 'recovery-key-btn', 'recovery-key', 'recovery-key-name']) {
    nodes.set(`s3-backup-${name}`, { value: '', files: [], hidden: false, textContent: '', disabled: false });
  }
  nodes.get('s3-backup-list').value = 'synthetic.alles-backup';
  nodes.get('s3-backup-recovery-key').files = [keyFile];
  const requests = [];
  const notices = [];
  let response;
  const context = {
    document: { getElementById: id => nodes.get(id) },
    FormData: class {
      fields = [];
      append(...field) { this.fields.push(field); }
    },
    _fetchWithRecentOwner: async (url, options) => { requests.push({ url, options }); return response; },
    toast: (message, kind) => notices.push({ message, kind }),
  };
  runInNewContext(`${s3Source.replace(/^export /gm, '')}\n_s3Configured = true; _s3Backups = [{ filename: 'synthetic.alles-backup' }]; globalThis.restore = restoreS3Backup;`, context);
  const restoreId = '0123456789abcdef0123456789abcdef';
  for (const data of [{}, null, { status: 'staged' }, { status: 'complete', restore_id: restoreId }, { status: 'staged', restore_id: '../invalid' }, { status: 'staged', restore_id: [restoreId] }]) {
    response = { ok: true, json: async () => data };
    await context.restore();
    assert.equal(nodes.get('s3-backup-restore-status').textContent, 'could not verify the backup response');
    assert.equal(notices.at(-1).kind, 'error');
    assert.equal(nodes.get('s3-backup-restore-btn').disabled, false);
  }
  response = { ok: true, json: async () => { throw new SyntaxError('synthetic invalid JSON'); } };
  await context.restore();
  assert.equal(nodes.get('s3-backup-restore-status').textContent, 'could not verify the backup response');
  response = { ok: false, json: async () => ({ detail: 'synthetic verification refused' }) };
  await context.restore();
  assert.equal(nodes.get('s3-backup-restore-status').textContent, 'synthetic verification refused');
  for (const applyCommand of [undefined, `alles restore apply ${restoreId}`, {}, ['wrong command'], 42, `alles restore apply ${'f'.repeat(32)}`]) {
    response = { ok: true, json: async () => ({ status: 'staged', restore_id: restoreId, apply_command: applyCommand }) };
    await context.restore();
    assert.equal(nodes.get('s3-backup-restore-status').textContent, `verified and staged. live data is unchanged. stop Alles, then run: alles restore apply ${restoreId}`);
    assert.equal(notices.at(-1).kind, 'success');
  }
  assert.equal(requests[0].url, '/api/backup/s3/restore');
  assert.equal(requests[0].options.method, 'POST');
  assert.deepEqual(requests[0].options.body.fields, [['filename', 'synthetic.alles-backup'], ['recovery_key', keyFile, keyFile.name]]);
  assert.equal(nodes.get('s3-backup-recovery-key').value, '');
  assert.equal(nodes.get('s3-backup-recovery-key-name').textContent, 'no separate key selected');
});

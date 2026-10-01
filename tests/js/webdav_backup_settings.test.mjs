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
  normalizeWebdavBackupConfig,
  webdavBackupConfigPayload,
  webdavBackupsFromResponse,
} = await import('../../static/js/settings.js');

const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const source = readFileSync(new URL('../../static/js/settings/backups.js', import.meta.url), 'utf8');

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

test('webdav local validation keeps the password for a corrected-only retry and submitted failures clear it', async () => {
  const nodes = new Map();
  for (const name of ['url', 'username', 'password', 'status', 'save-btn']) {
    nodes.set(`webdav-backup-${name}`, { value: '', disabled: false, textContent: '', style: {} });
  }
  const field = name => nodes.get(`webdav-backup-${name}`);
  field('url').value = 'http://dav.example.test/alles';
  field('username').value = 'jx';
  field('password').value = 'example-password';
  const requests = [];
  const notices = [];
  let release;
  const context = {
    document: { getElementById: id => nodes.get(id) },
    URL,
    toast: (message, kind) => notices.push({ message, kind }),
    _fetchWithRecentOwner: (url, options) => {
      assert.equal(field('password').value, '');
      requests.push({ url, options });
      return new Promise(resolve => { release = resolve; });
    },
  };
  const webdavSource = source.slice(source.indexOf('// ── webdav backup'), source.indexOf('// ── s3 backup'));
  runInNewContext(`${webdavSource.replace(/^export /gm, '')}\n_webdavDirty = true; globalThis.save = saveWebdavBackup;`, context);

  await context.save();
  assert.equal(requests.length, 0);
  assert.equal(field('password').value, 'example-password');
  assert.equal(field('status').textContent, 'the WebDAV url must use https');
  assert.equal(field('save-btn').disabled, false);

  field('url').value = 'https://dav.example.test/alles';
  const saving = context.save();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/backup/webdav');
  assert.equal(requests[0].options.method, 'PUT');
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    url: 'https://dav.example.test/alles', username: 'jx', password: 'example-password',
  });
  assert.equal(field('save-btn').disabled, true);
  await context.save();
  assert.equal(requests.length, 1);
  release({ ok: false, json: async () => ({ detail: 'synthetic save refused' }) });
  await saving;
  assert.equal(field('save-btn').disabled, false);
  assert.equal(field('password').value, '');
  assert.equal(field('status').textContent, 'synthetic save refused');
  assert.equal(notices.at(-1).kind, 'error');
});

test('webdav mutations reconcile reopening during the write or its list read', async t => {
  for (const action of ['save', 'run']) {
    for (const timing of ['mutation', 'list']) {
      await t.test(`${action}: reopened during ${timing}`, async () => {
        const nodes = new Map();
        for (const name of ['card', 'url', 'username', 'password', 'status', 'save-btn', 'disconnect-btn', 'run-btn', 'list', 'selection', 'restore-btn', 'refresh-btn']) {
          const id = `webdav-backup-${name}`;
          nodes.set(id, {
            id, value: '', disabled: false, hidden: false, textContent: '', style: {},
            listeners: {}, addEventListener(type, listener) { this.listeners[type] = listener; },
          });
        }
        const field = name => nodes.get(`webdav-backup-${name}`);
        const config = { configured: true, url: 'https://dav.example.test/alles', username: 'example' };
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
            if (url === '/api/backup/webdav') { configReads += 1; return response(config); }
            assert.equal(url, '/api/backup/webdav/backups');
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
        runInNewContext(`${source.replace(/^import .*;\n/gm, '').replace(/^export /gm, '')}\nglobalThis.pane = createBackupPane(() => {}); globalThis.mutate = ${action === 'save' ? 'saveWebdavBackup' : 'runWebdavBackup'};`, context);
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
        field('username').value = 'newer-draft';
        field('card').listeners.input({ target: field('username') });
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
        assert.equal(field('username').value, 'newer-draft');
        assert.equal(field('status').textContent, action === 'save' ? 'saved; newer connection edits kept here' : 'backup uploaded and verified');
        assert.equal(field('restore-btn').disabled, false);
        assert.equal(field('refresh-btn').disabled, false);
        assert.equal(configReads, 1);
      });
    }
  }
});

test('webdav restores require a staged receipt and derive its command from the validated id', async () => {
  const nodes = new Map();
  const keyFile = { name: 'synthetic-recovery.key' };
  for (const name of ['list', 'restore-status', 'restore-btn', 'save-btn', 'disconnect-btn', 'run-btn', 'refresh-btn', 'recovery-key-btn', 'recovery-key', 'recovery-key-name']) {
    nodes.set(`webdav-backup-${name}`, { value: '', files: [], hidden: false, textContent: '', disabled: false });
  }
  nodes.get('webdav-backup-list').value = 'synthetic.alles-backup';
  nodes.get('webdav-backup-recovery-key').files = [keyFile];
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
  const webdavSource = source.slice(source.indexOf('// ── webdav backup'), source.indexOf('// ── s3 backup'));
  runInNewContext(`${webdavSource.replace(/^export /gm, '')}\n_webdavConfigured = true; _webdavBackups = [{ filename: 'synthetic.alles-backup' }]; globalThis.restore = restoreWebdavBackup;`, context);
  const restoreId = '0123456789abcdef0123456789abcdef';
  for (const data of [{}, null, { status: 'staged' }, { status: 'complete', restore_id: restoreId }, { status: 'staged', restore_id: '../invalid' }, { status: 'staged', restore_id: [restoreId] }]) {
    response = { ok: true, json: async () => data };
    await context.restore();
    assert.equal(nodes.get('webdav-backup-restore-status').textContent, 'could not verify the backup response');
    assert.equal(notices.at(-1).kind, 'error');
    assert.equal(nodes.get('webdav-backup-restore-btn').disabled, false);
  }
  response = { ok: true, json: async () => { throw new SyntaxError('synthetic invalid JSON'); } };
  await context.restore();
  assert.equal(nodes.get('webdav-backup-restore-status').textContent, 'could not verify the backup response');
  response = { ok: false, json: async () => ({ detail: 'synthetic verification refused' }) };
  await context.restore();
  assert.equal(nodes.get('webdav-backup-restore-status').textContent, 'synthetic verification refused');
  for (const applyCommand of [undefined, `alles restore apply ${restoreId}`, {}, ['wrong command'], 42, `alles restore apply ${'f'.repeat(32)}`]) {
    response = { ok: true, json: async () => ({ status: 'staged', restore_id: restoreId, apply_command: applyCommand }) };
    await context.restore();
    assert.equal(nodes.get('webdav-backup-restore-status').textContent, `verified and staged. live data is unchanged. stop Alles, then run: alles restore apply ${restoreId}`);
    assert.equal(notices.at(-1).kind, 'success');
  }
  assert.equal(requests[0].url, '/api/backup/webdav/restore');
  assert.equal(requests[0].options.method, 'POST');
  assert.deepEqual(requests[0].options.body.fields, [['filename', 'synthetic.alles-backup'], ['recovery_key', keyFile, keyFile.name]]);
  assert.equal(nodes.get('webdav-backup-recovery-key').value, '');
  assert.equal(nodes.get('webdav-backup-recovery-key-name').textContent, 'no separate key selected');
});

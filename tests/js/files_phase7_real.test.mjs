import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const files = readFileSync(new URL('../../static/js/filesphase7.js', import.meta.url), 'utf8');
const dialog = readFileSync(new URL('../../static/js/dialog.js', import.meta.url), 'utf8');
const css = readFileSync(new URL('../../static/kokuen.css', import.meta.url), 'utf8');
const serviceWorker = readFileSync(new URL('../../static/sw.js', import.meta.url), 'utf8');

function locationFocusHarness() {
  const document = { body: {}, activeElement: null };
  const state = {
    locationId: 'first',
    locations: ['first', 'second'].map(id => ({ id, name: id, kind: 'local', access: 'managed' })),
  };
  const focused = [];
  const host = {
    children: [], hidden: false,
    contains(node) { return this.children.includes(node); },
    querySelectorAll() { return this.children; },
    set innerHTML(value) {
      if (this.contains(document.activeElement)) document.activeElement = document.body;
      this.children = [...value.matchAll(/data-location-id="([^"]+)"/g)].map(([, id]) => ({
        dataset: { locationId: id },
        focus(options) { document.activeElement = this; focused.push({ id, ...options }); },
      }));
    },
  };
  const source = files.match(/function renderLocations\(\) \{[\s\S]*?\n\}/)[0];
  const context = vm.createContext({
    document, state, $: id => id === 'files-location-list' ? host : null,
    esc: value => String(value), locationIcon: () => '',
  });
  vm.runInContext(source + '\nglobalThis.render = renderLocations;', context);
  context.render();
  return { ...context, host, focused };
}

test('changing Files location preserves the focused location through the list redraw', () => {
  const h = locationFocusHarness();
  const original = h.host.children[1];
  h.document.activeElement = original;
  h.state.locationId = 'second';
  h.render();
  assert.notEqual(h.document.activeElement, original);
  assert.equal(h.document.activeElement, h.host.children[1]);
  assert.deepEqual(h.focused, [{ id: 'second', preventScroll: true }]);
});

test('refreshing Files locations does not take focus from another control', () => {
  const h = locationFocusHarness();
  const search = { dataset: { locationId: 'second' } };
  h.document.activeElement = search;
  h.render();
  assert.equal(h.document.activeElement, search);
  assert.deepEqual(h.focused, []);
});

test('a removed or hidden Files location is not chosen as a focus destination', () => {
  for (const locations of [['first'], ['first', 'third']]) {
    const h = locationFocusHarness();
    h.document.activeElement = h.host.children[1];
    h.state.locations = locations.map(id => ({ id, name: id, kind: 'local' }));
    h.render();
    assert.equal(h.document.activeElement, h.document.body);
    assert.deepEqual(h.focused, []);
  }
});

test('durable Files and storage-location mutations stay out of offline replay', () => {
  const noqueueLiteral = serviceWorker.match(/const NOQUEUE = (\[[^;]+\]);/)?.[1] || '[]';
  const noqueue = Function(`return ${noqueueLiteral}`)();
  const staysOnline = pathname => noqueue.some(prefix => pathname.startsWith(prefix));

  for (const pathname of [
    '/api/files/operations',
    '/api/files/operations/operation-id',
    '/api/files/operations/operation-id/run',
    '/api/files/operations/operation-id/cancel',
    '/api/files/operations/operation-id/retry',
    '/api/files/operations/operation-id/undo',
    '/api/storage-locations',
    '/api/storage-locations/location-id',
    '/api/storage-locations/location-id/test',
    '/api/storage-locations/location-id/index',
    '/api/vault-transfer/import/preview',
    '/api/vault-transfer/import',
    '/api/money/accounts',
    '/api/money/transactions',
    '/api/money/transfer',
    '/api/subscriptions',
    '/api/subscriptions/subscription-id',
    '/api/finance/actual/cutover',
    '/api/finance/actual/rollback',
    '/api/finance/imports/batch-id/apply',
    '/api/finance/imports/batch-id/undo',
    '/api/finance/connections/connection-id/sync',
    '/api/system/searxng/stop',
    '/api/system/searxng/update',
    '/api/system/searxng/uninstall',
    '/api/system/services/searxng/uninstall',
    '/api/system/companions/adguard-home/activate',
  ]) {
    assert.equal(staysOnline(pathname), true, pathname);
  }
  assert.equal(staysOnline('/api/files/tags'), false);
  assert.match(serviceWorker, /!NOQUEUE\.some\(p => replayPath\.startsWith\(p\)\)/);
});

test('flush quarantines stale forbidden outbox rows without replaying or deleting them', async () => {
  const deleted = [];
  const blocked = [];
  const fetched = [];
  const rows = [
    {
      id: 1,
      url: 'https://alles.test/api/storage-locations/location-id',
      method: 'DELETE',
      headers: {},
      body: '',
    },
    {
      id: 2,
      url: 'https://alles.test/api/files/tags',
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{}',
    },
    {
      id: 3,
      url: 'https://alles.test/api/system/searxng/restart',
      method: 'POST',
      headers: {},
      body: '',
    },
    {
      id: 4,
      url: 'https://alles.test/api/files%2Foperations/operation-id',
      method: 'POST',
      headers: {},
      body: '',
    },
    {
      id: 5,
      url: 'https://alles.test/api/%2566inance/actual/cutover',
      method: 'POST',
      headers: {},
      body: '',
    },
    {
      id: 6,
      url: 'https://alles.test/api/%E0%A4%A',
      method: 'POST',
      headers: {},
      body: '',
    },
    {
      id: 7,
      url: 'https://alles.test/api/money/transactions',
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{}',
    },
    {
      id: 8,
      url: 'https://alles.test/api/subscriptions/subscription-id',
      method: 'DELETE',
      headers: {},
      body: '',
    },
  ];
  const context = vm.createContext({
    URL, Response,
    self: { addEventListener() {}, location: { origin: 'https://alles.test' } },
    fetch: async url => { fetched.push(url); return new Response('{}'); },
    getAll: async () => rows,
    remove: async id => { deleted.push(id); },
    put: async item => { blocked.push(item); },
  });
  vm.runInContext(serviceWorker + `
    _all = getAll; _del = remove; _put = put; notifyClients = async () => {};
    globalThis.flush = flushOutbox;
  `, context);
  const flush = context.flush;

  await flush();

  assert.deepEqual(fetched, ['https://alles.test/api/files/tags']);
  assert.deepEqual(deleted, [2]);
  assert.deepEqual(blocked.map(item => item.id), [1, 3, 4, 5, 6, 7, 8]);
  assert.ok(blocked.every(item => item.blocked_reason === 'replay_policy_changed'));
});

test('only an explicit owner action discards one retained outbox row', async () => {
  const deleted = [];
  let notified = 0;
  const rows = [
    { id: 1, blocked_reason: 'replay_policy_changed' },
    { id: 2 },
    { id: 3, blocked_reason: 'conflict' },
  ];
  const context = vm.createContext({
    self: { addEventListener() {} },
    getAll: async () => rows,
    remove: async id => { deleted.push(id); },
    notify: async () => { notified += 1; },
  });
  vm.runInContext(serviceWorker + `
    _all = getAll; _del = remove; notifyClients = notify;
    globalThis.discard = discardOutboxItem;
  `, context);
  await context.discard(1);
  await context.discard(2);
  await context.discard(999);
  assert.deepEqual(deleted, [1]);
  assert.equal(notified, 3);
  assert.match(serviceWorker, /alles-discard-outbox/);
});

test('network-first code preserves 4xx, but uses cache for server failure or offline', async () => {
  const source = serviceWorker.match(/async function networkFirstStatic\(request\) \{[\s\S]*?\n\}/)?.[0] || '';
  const cached = { source: 'cached' };
  let matchCalls = 0;
  let putCalls = 0;
  const cache = {
    match: async () => { matchCalls += 1; return cached; },
    put: async () => { putCalls += 1; },
  };
  const request = { url: 'https://alles.test/static/js/removed.js' };
  const missing = { ok: false, status: 404 };
  const runMissing = Function(
    'caches', 'fetch', 'CACHE',
    `${source}\nreturn networkFirstStatic;`,
  )(
    { open: async () => cache },
    async () => missing,
    'alles-test',
  );
  assert.equal(await runMissing(request), missing);
  assert.equal(matchCalls, 0);
  assert.equal(putCalls, 0);

  const runServerFailure = Function(
    'caches', 'fetch', 'CACHE',
    `${source}\nreturn networkFirstStatic;`,
  )(
    { open: async () => cache },
    async () => ({ ok: false, status: 503 }),
    'alles-test',
  );
  assert.equal(await runServerFailure(request), cached);
  assert.equal(matchCalls, 1);

  const runOffline = Function(
    'caches', 'fetch', 'CACHE',
    `${source}\nreturn networkFirstStatic;`,
  )(
    { open: async () => cache },
    async () => { throw new Error('offline'); },
    'alles-test',
  );
  assert.equal(await runOffline(request), cached);
  assert.equal(matchCalls, 2);
});

test('Files renders zero-byte sizes without inventing missing values', () => {
  const source = files.match(/function formatSize\(value\) \{[\s\S]*?\n\}/)?.[0] || '';
  const formatSize = Function(`${source}; return formatSize;`)();
  assert.equal(formatSize(0), '0 B');
  assert.equal(formatSize(undefined), '');
  assert.equal(formatSize('not-a-number'), '');
});

test('the real Files screen uses the Phase 7 multi-location workbench', () => {
  for (const id of [
    'files-location-list',
    'files-browser',
    'files-selection-bar',
    'files-detail-panel',
    'files-operation-dock',
    'files-location-dialog',
    'files-transfer-dialog',
  ]) {
    assert.match(html, new RegExp(`id="${id}"`), id);
  }
  assert.match(app, /from '\.\/filesphase7\.js\?v=485'/);
  assert.doesNotMatch(html.match(/id="files-view"[\s\S]*?<\/div>\s*\n\s*<!-- ── mail view/)[0], /<select\b|type="(?:checkbox|radio)"/i);
});

test('Files exposes the reviewed external Obsidian vault workflow', () => {
  const view = html.match(/id="files-view"[\s\S]*?<\/div>\s*\n\s*<!-- ── mail view/)[0];
  for (const label of ['keep external', 'copy into Alles', 'move into Alles']) {
    assert.match(view, new RegExp(label));
  }
  assert.match(files, /\/api\/vault-transfer\/import\/preview/);
  assert.match(files, /\/api\/vault-transfer\/import/);
  assert.match(files, /\/api\/vault-transfer\/\$\{encodeURIComponent\(vaultTransferId\)\}\/rollback/);
  assert.match(files, /the vault change was rolled back/);
  assert.match(files, /relative links and file bytes stay unchanged/);
  assert.match(files, /preview\.required_bytes/);
  assert.match(css, /\.files-choice-field\[hidden\] \{ display: none; \}/);
  assert.doesNotMatch(view, /type="(?:checkbox|radio)"/i);
});

test('Files selection keeps a compact glyph inside a full-size accessible target', () => {
  assert.match(css, /\.files-check \{[\s\S]*?width: var\(--k-control\);[\s\S]*?height: var\(--k-control\)/);
  assert.match(css, /\.files-check::before \{[\s\S]*?width: 16px;[\s\S]*?height: 16px/);
});

test('Files owns the approved app header instead of the legacy app crumb', () => {
  const view = html.match(/id="files-view"[\s\S]*?<\/div>\s*\n\s*<!-- ── mail view/)[0];
  for (const id of [
    'files-app-header',
    'files-breadcrumb',
    'files-app-status',
    'files-settings-btn',
  ]) {
    assert.match(view, new RegExp(`id="${id}"`), id);
  }
  assert.match(css, /body\[data-app="files"\] \.main > \.topbar\s*\{\s*display:\s*none\s*!important;/);
  assert.doesNotMatch(view, /id="files-home-btn"/);
  assert.match(view, /id="files-settings-dialog"[^>]*role="dialog"/);
  assert.doesNotMatch(app, /getElementById\('files-settings-btn'\)/);
});

test('Files sends location identity through reads and writes', () => {
  assert.match(files, /location_id/);
  assert.match(files, /\/api\/storage-locations/);
  assert.match(files, /\/api\/files\/operations/);
  assert.match(files, /\/api\/files\/offline/);
  assert.match(files, /files-upload-input/);
  assert.match(files, /\/api\/storage-locations\/\$\{encodeURIComponent\(locationId\)\}\/index/);
});

test('selection, transfer, offline, and operation recovery are first-class UI states', () => {
  for (const name of [
    'toggleSelection',
    'openTransferDialog',
    'toggleOffline',
    'loadOperations',
    'undoOperation',
  ]) {
    assert.match(files, new RegExp(`function ${name}|const ${name}`), name);
  }
  assert.match(css, /\.files-phase7-workbench/);
  assert.match(css, /\.files-phase7-workbench \{[\s\S]{0,80}position:\s*relative;/);
  assert.match(css, /\.files-phase7-location-panel/);
  assert.match(css, /@media\s*\(max-width:\s*760px\)/);
  assert.match(files, /const refreshContext =/);
  assert.match(files, /if \(sameView \|\| currentViewAffected\)\s*\{/);
});

test('Files rows use the same full browser width as the table header', () => {
  const phase7 = css.slice(css.indexOf('/* Phase 7 Files:'));
  assert.match(
    phase7,
    /body\[data-app="files"\] #files-view \.files-list \{[\s\S]{0,220}width:\s*100%;[\s\S]{0,80}margin-inline:\s*0;/,
  );
});

test('copy and move require an explicit destination instead of selecting the source by default', () => {
  const open = files.match(/function openTransferDialog\(action\)[\s\S]*?\n}\n\nasync function submitTransfer/)?.[0] || '';
  assert.match(open, /aria-checked="false"/);
  assert.doesNotMatch(open, /aria-checked="\$\{index === 0\}"/);
});

test('operation refreshes reload filtered Starred and Offline backing collections', () => {
  assert.match(
    files,
    /async function refreshAfterOperation\(searchTerm = state\.searchTerm\)[\s\S]*?if \(\['starred', 'offline'\]\.includes\(state\.view\) && searchTerm\)[\s\S]*?return loadCurrentView\(\)/,
  );
  const queue = files.match(/async function queueOperation\(payload\)[\s\S]*?\n}\n\nasync function loadOperations/)?.[0] || '';
  assert.match(queue, /await refreshAfterOperation\(refreshTerm\)/);
  const action = files.match(/async function operationAction\(id, action\)[\s\S]*?\n}\n\nasync function undoOperation/)?.[0] || '';
  assert.match(action, /refreshAfterOperation\(\)/);
});

test('cached descendants cannot create overlapping offline requests', () => {
  const toggle = files.match(/async function toggleOffline\(item\)[\s\S]*?\n}\n\nasync function setStar/)[0];
  assert.match(toggle, /item\.cache_only && !current/);
  assert.match(toggle, /return/);
  const writeState = files.match(/function applyWriteState\(\)[\s\S]*?\n}\n\nfunction renderFilesLoading/)[0];
  assert.match(writeState, /cacheOnlyDescendant/);
  assert.match(writeState, /action === 'offline'/);
});

test('existing offline copies expose separate refresh and remove actions', () => {
  const details = files.match(/function renderDetails\(item\)[\s\S]*?\n}\n\nfunction closeDetails/)?.[0] || '';
  assert.match(details, /data-detail-action="offline-refresh"/);
  assert.match(details, /refresh offline copy/);
  assert.match(details, /data-detail-action="offline-remove"/);
  const setOffline = files.match(/async function setOffline\(item[^)]*\)[\s\S]*?\n}\n\nasync function keepItemsOffline/)?.[0] || '';
  assert.match(setOffline, /action === 'remove'/);
  assert.match(setOffline, /jsonOptions\('POST'/);
});

test('bulk offline work is awaited sequentially and refreshes once', () => {
  const bulk = files.match(/async function keepItemsOffline\(items\)[\s\S]*?\n}\n/)?.[0] || '';
  assert.match(bulk, /for \(const item of items\)/);
  assert.match(bulk, /await setOffline\(item, 'keep', false\)/);
  assert.match(bulk, /await loadCurrentView\(\)/);
  const events = files.match(/function bindEvents\(\)[\s\S]*?\n}\n\nexport function initFiles/)?.[0] || '';
  assert.match(events, /keepItemsOffline\(\[\.\.\.state\.selected\.values\(\)\]\)/);
  assert.doesNotMatch(events, /forEach\(toggleOffline\)/);
});

test('Files keyboard rows and Photos handoff expose only valid actions', () => {
  assert.match(files, /class="file-row[^`]*tabindex="0"/);
  assert.match(files, /event\.target !== row/);
  assert.match(files, /function canSendToPhotos/);
  assert.match(files, /if \(item\.type === 'dir'\) return true/);
  assert.match(files, /canSendToPhotos\(item\)/);
});

test('Files prompts use labelled custom dialogs with trapped focus', () => {
  assert.match(dialog, /role="dialog" aria-modal="true" aria-labelledby=/);
  assert.match(dialog, /role="alertdialog" aria-modal="true" aria-labelledby=/);
  assert.match(dialog, /event\.key === 'Escape'/);
  assert.match(dialog, /event\.key !== 'Tab'/);
  assert.match(dialog, /previousFocus\?\.focus\?\.\(\)/);
});

test('Files location and transfer modals trap and restore focus too', () => {
  assert.match(files, /const dialogReturnFocus = new Map\(\)/);
  assert.match(files, /function openFilesDialog/);
  assert.match(files, /function trapFilesDialogFocus/);
  assert.match(files, /dialogReturnFocus\.get\(name\)\?\.focus\?\.\(\)/);
});

test('Files loading and error states preserve the list shape and offer recovery', () => {
  assert.match(files, /function renderFilesLoading/);
  assert.match(files, /function renderFilesError/);
  assert.match(files, /data-files-retry/);
  assert.match(css, /\.files-loading-row/);
  assert.match(css, /--k-row:\s*46px/);
});

test('Files details preserve keyboard context and search has an accessible name', () => {
  assert.match(html, /id="files-search"[^>]*aria-label="search files"/);
  assert.match(files, /detailReturnPath/);
  assert.match(files, /\$\('files-detail-close'\)\?\.focus\(\)/);
  assert.match(files, /document\.querySelector\(`\.file-row\[data-path=/);
});

test('Files notices never cover the durable transfer panel', () => {
  assert.match(css, /body\[data-app="files"\]:has\(#files-operation-dock:not\(\[hidden\]\)\) \.toast-container/);
});

test('Files clears stale search state when the view or location changes', () => {
  assert.match(files, /let searchSequence = 0/);
  assert.match(files, /let viewSequence = 0/);
  assert.match(files, /const sequence = \+\+searchSequence/);
  assert.match(files, /if \(sequence !== searchSequence \|\| locationId !== state\.locationId \|\| view !== state\.view\) return/);
  assert.match(files, /if \(sequence !== viewSequence \|\| locationId !== state\.locationId\) return/);
  assert.match(files, /showNotice\(''\)/);
  assert.match(files, /renderFilesLoading\(host\)/);
  assert.match(files, /if \(!q\) \{\s*searchSequence \+= 1;\s*return loadCurrentView\(\);\s*\}/);
  assert.match(files, /view !== state\.view/);
  assert.match(files, /cwd !== state\.cwd/);
  assert.match(files, /function clearFilesSearch/);
  assert.match(
    files,
    /state\.locationId = button\.dataset\.locationId;[\s\S]{0,240}clearFilesSearch\(\);/,
  );
  assert.match(
    files,
    /state\.view = button\.dataset\.filesView;[\s\S]{0,240}clearFilesSearch\(\);/,
  );
});

test('Files row double-click ignores nested controls', () => {
  assert.match(
    files,
    /addEventListener\('dblclick',[\s\S]{0,300}event\.target\.closest\([^)]*(?:button|data-file-select|data-file-open)/,
  );
});

test('Files clears actionable selections before changing views', () => {
  assert.match(
    files,
    /state\.view = button\.dataset\.filesView;[\s\S]{0,180}state\.selected\.clear\(\);[\s\S]{0,120}renderSelection\(\);[\s\S]{0,120}loadCurrentView\(\);/,
  );
});

test('Files uses durable state instead of stacking redundant success notices', () => {
  assert.doesNotMatch(files, /toast\(`\$\{payload\.action\} complete`/);
  assert.doesNotMatch(files, /toast\('location added'/);
  assert.doesNotMatch(files, /toast\('available offline'/);
  assert.doesNotMatch(files, /toast\('offline copy removed'/);
});

test('Files detail open navigates into directories', () => {
  assert.match(files, /data-detail-action="open"/);
  const handler = files.match(/\$\('files-detail-content'\)\?\.addEventListener\('click'[\s\S]*?\n  \}\);/)[0];
  assert.match(handler, /action === 'open'/);
  assert.match(handler, /item\.type === 'dir'/);
  assert.match(handler, /openItem\(item\)/);
});

test('Files text previews ignore stale responses', () => {
  assert.match(files, /let previewSequence = 0/);
  assert.match(files, /const sequence = \+\+previewSequence/);
  assert.match(
    files,
    /await request\(readEndpoint[\s\S]{0,260}if \(sequence !== previewSequence \|\| path !== state\.previewPath\) return/,
  );
});

test('Files transfer and delete enqueue failures stay visible and handled', () => {
  const transfer = files.match(/async function submitTransfer\(\)[\s\S]*?\n}\n\nasync function queueOperation/)[0];
  assert.match(transfer, /try\s*{/);
  assert.match(transfer, /catch \(error\)/);
  assert.ok(transfer.indexOf("closeDialog('transfer')") > transfer.lastIndexOf('await queueOperation'));
  const deletion = files.match(/async function deleteItems\(items\)[\s\S]*?\n}\n\nasync function restoreItem/)[0];
  assert.match(deletion, /catch \(error\)/);
  assert.match(deletion, /toast\(error\.message, 'error'\)/);
});

test('Files preview close stops and removes active media', () => {
  assert.match(files, /function closePreview\(/);
  assert.match(files, /querySelectorAll\('audio, video'\)/);
  assert.match(files, /media\.pause\(\)/);
  assert.match(files, /body\.replaceChildren\(\)/);
  assert.match(files, /files-preview-close'[\s\S]{0,120}closePreview/);
  assert.match(
    files,
    /files-preview-modal'[\s\S]{0,180}event\.target === previewModal[\s\S]{0,100}closePreview\(\)/,
  );
});

test('Files never offers or runs trash restore on a read-only location', () => {
  const details = files.match(/async function renderDetails\(item\)[\s\S]*?\n}\n\nasync function loadVersions/)[0];
  const restore = files.match(/async function restoreItem\(item, \{ close = true \} = \{\}\)[\s\S]*?\n}\n\nfunction photosImportMessage/)[0];
  assert.match(details, /state\.view === 'trash'[\s\S]{0,180}writable[\s\S]{0,180}data-detail-action="restore"/);
  assert.match(restore, /if \(!isWritable\(\)\) return/);
});

test('Files preview is a focus-managed modal', () => {
  assert.match(html, /id="files-preview-modal"[^>]*role="dialog"[^>]*aria-modal="true"[^>]*aria-labelledby="files-preview-name"/);
  assert.match(files, /let previewReturnFocus = null/);
  assert.match(files, /previewReturnFocus = document\.activeElement/);
  assert.match(files, /\$\('files-preview-close'\)\?\.focus\(\)/);
  assert.match(files, /trapFilesDialogFocus\(event, previewModal\)/);
  assert.match(files, /previewReturnFocus\?\.focus\?\.\(\)/);
});

test('Files preview focus trap includes interactive media and embedded documents', () => {
  const focusables = files.match(/function dialogFocusables\(dialog\)[\s\S]*?\n}/)[0];
  assert.match(focusables, /audio\[controls\]/);
  assert.match(focusables, /video\[controls\]/);
  assert.match(focusables, /iframe/);
});

test('Files reports every part of a mixed Photos import', () => {
  const source = files.match(/function photosImportMessage\(result\)[\s\S]*?\n}/)[0];
  const message = Function(`return (${source.replace(/^function photosImportMessage/, 'function')})`)();
  assert.equal(
    message({ imported: 1, skipped: 1, ignored: 1, failed: [{ error: 'broken' }] }),
    '1 item sent to Photos · 1 already there · 1 unsupported file skipped · 1 failed',
  );
  assert.equal(message({ imported: 0, skipped: 2, ignored: 0, failed: [] }), '2 already there');
  assert.equal(message({ imported: 0, skipped: 0, ignored: 0, failed: [] }), 'nothing sent to Photos');
});

test('Files mutations capture their location and folder before awaiting', () => {
  const deletion = files.match(/async function deleteItems\(items\)[\s\S]*?\n}\n\nasync function restoreItem/)[0];
  assert.match(deletion, /const locationId = state\.locationId/);
  assert.match(deletion, /source_location_id: locationId/);
  assert.match(deletion, /state\.selected\.clear\(\);\s*renderSelection\(\);/);

  const upload = files.match(/async function uploadFiles\(files\)[\s\S]*?\n}\n\nfunction wireChoiceGroup/)[0];
  assert.match(upload, /const locationId = state\.locationId/);
  assert.match(upload, /const cwd = state\.cwd/);
  assert.match(upload, /sendUpload\(file, file\.name, locationId, cwd\)/);
  assert.match(upload, /reviewUpload\(file, locationId, cwd, error\)/);
  assert.match(upload, /state\.locationId === locationId[\s\S]*state\.cwd === cwd/);

  const transfer = files.match(/async function submitTransfer\(\)[\s\S]*?\n}\n\nasync function queueOperation/)[0];
  assert.match(transfer, /const sourceLocationId = state\.locationId/);
  assert.match(transfer, /const action = state\.transferAction/);
  assert.match(transfer, /action: action/);
  assert.match(transfer, /source_location_id: sourceLocationId/);
});

test('Files search invalidates an older listing request', () => {
  const search = files.match(/async function searchFiles\(term\)[\s\S]*?\n}\n\nfunction clearFilesSearch/)[0];
  assert.match(search, /viewSequence \+= 1/);
});

test('Files failed search clears rows that belonged to the previous view', () => {
  const search = files.match(/async function searchFiles\(term\)[\s\S]*?\n}\n\nfunction clearFilesSearch/)[0];
  const failure = search.match(/catch \(error\) \{[\s\S]*?\n  \}/)[0];
  assert.match(failure, /state\.items = \[\]/);
  assert.match(failure, /state\.selected\.clear\(\)/);
  assert.ok(failure.indexOf('state.items = []') < failure.indexOf('renderFilesError'));
});

test('Files index status stays bound to the location that started the request', () => {
  const status = files.match(/async function loadIndexStatus\([^)]*\)[\s\S]*?\n}\n\nfunction scheduleIndexPoll/)[0];
  assert.match(status, /const locationId =/);
  assert.match(status, /encodeURIComponent\(locationId\)/);
  assert.match(status, /if \(locationId !== state\.locationId \|\|/);
  assert.match(status, /state\.indexStatus\.set\(locationId, status\)/);

  const start = files.match(/async function startIndexing\([^)]*\)[\s\S]*?\n}\n\nfunction applyWriteState/)[0];
  assert.match(start, /const locationId =/);
  assert.match(start, /if \(locationId !== state\.locationId \|\|/);
  assert.match(start, /state\.indexStatus\.set\(locationId, status\)/);
});

test('Files index status rejects responses older than a start mutation', () => {
  const status = files.match(/async function loadIndexStatus\([^)]*\)[\s\S]*?\n}\n\nfunction scheduleIndexPoll/)[0];
  const start = files.match(/async function startIndexing\([^)]*\)[\s\S]*?\n}\n\nfunction applyWriteState/)[0];
  assert.match(files, /const indexRevision = new Map\(\)/);
  assert.match(status, /const revision = indexRevision\.get\(locationId\) \|\| 0/);
  assert.match(status, /revision !== \(indexRevision\.get\(locationId\) \|\| 0\)/);
  assert.match(start, /indexRevision\.set\(locationId, revision\)/);
  assert.match(start, /revision !== \(indexRevision\.get\(locationId\) \|\| 0\)/);
  assert.ok(start.indexOf('revision += 1') < start.indexOf('state.indexStatus.set(locationId, status)'));
});

test('Files starts the new location listing without waiting for index status', () => {
  const handler = files.match(/\$\('files-location-list'\)\?\.addEventListener\('click',[\s\S]*?\n  }\);/)[0];
  assert.ok(handler.indexOf("loadFiles('')") < handler.indexOf('loadIndexStatus('));
  assert.doesNotMatch(handler, /await loadIndexStatus/);
});

test('Files initial location loading does not wait for optional index telemetry', () => {
  const locations = files.match(/async function loadLocations\([^)]*\)[\s\S]*?\n}\n\nfunction renderLocations/)[0];
  assert.match(locations, /void loadIndexStatus\(state\.locationId\)/);
  assert.doesNotMatch(locations, /loadIndexStatus\(state\.locationId, fetcher\)/);
  assert.doesNotMatch(locations, /await loadIndexStatus/);
});

test('Files awaits its first operations request inside the specialist run', () => {
  const operations = files.match(/async function loadOperations\([^)]*\)[\s\S]*?\n}\n\nfunction renderOperations/)[0];
  assert.match(operations, /request\('\/api\/files\/operations\?limit=40', \{\}, fetcher\)/);
  const init = files.match(/export function initFiles\([^)]*\)[\s\S]*?\n}/)[0];
  assert.match(init, /const initialOperations = loadOperations\(fetcher\)/);
  assert.match(init, /return initialOperations/);
});

test('Files pauses operation polling while its view or tab is inactive', () => {
  const poll = files.match(/function pollOperations\(\)[\s\S]*?\n}/)?.[0] || '';
  assert.match(poll, /document\.visibilityState === 'hidden'/);
  assert.match(poll, /files-view/);
  assert.match(poll, /style\.display === 'none'/);
  assert.match(files, /setInterval\(pollOperations, 4000\)/);
});

test('Files async detail mutations ignore a changed location or closed detail panel', () => {
  const offline = files.match(/async function toggleOffline\(item\)[\s\S]*?\n}\n\nasync function setStar/)[0];
  assert.match(offline, /const locationId = state\.locationId/);
  assert.match(offline, /location_id: locationId/);
  assert.match(offline, /if \(locationId !== state\.locationId\) return/);

  const star = files.match(/async function setStar\(item\)[\s\S]*?\n}\n\nasync function renameItem/)[0];
  assert.match(star, /const locationId = state\.locationId/);
  assert.match(star, /if \(locationId !== state\.locationId\) return/);
  assert.match(star, /state\.current === item[\s\S]*!panel\.hidden/);
});

test('Files version results and failures cannot repaint a superseded detail', async () => {
  const source = files.match(/async function loadVersions\(path, locationId, detailRequest\)[\s\S]*?\n}/)[0];
  for (const outcome of ['resolve', 'reject']) {
    for (const change of ['none', 'sequence', 'location', 'item', 'hidden']) {
      const host = { innerHTML: 'original detail', querySelector: () => null, querySelectorAll: () => [] };
      const panel = { hidden: false };
      let finish;
      const pending = new Promise((resolve, reject) => { finish = outcome === 'resolve' ? resolve : reject; });
      const context = vm.createContext({
        state: { current: {}, locationId: 'original' }, detailSequence: 7,
        $: id => id === 'files-detail-panel' ? panel : host,
        request: () => pending, query: () => '', esc: value => value,
      });
      vm.runInContext(source + '\nglobalThis.load = loadVersions;', context);
      const result = context.load('notes.txt', 'original', 7);
      if (change === 'sequence') context.detailSequence += 1;
      if (change === 'location') context.state.locationId = 'other';
      if (change === 'item') context.state.current = {};
      if (change === 'hidden') panel.hidden = true;
      // Active error rendering needs a real retry button; stale errors must never query it.
      host.querySelector = () => outcome === 'reject' ? { addEventListener() {} } : null;
      finish(outcome === 'resolve' ? [] : new Error('version source unavailable'));
      await result;
      if (change !== 'none') assert.equal(host.innerHTML, 'original detail', `${outcome}: ${change}`);
      else if (outcome === 'resolve') assert.equal(host.innerHTML, '');
      else assert.match(host.innerHTML, /version history unavailable: version source unavailable/);
    }
  }
});

test('Files upload request keeps its captured destination and explicit reviewed identity', async () => {
  const source = files.match(/function sendUpload\([^)]*\)[\s\S]*?\n}/)[0];
  const sent = [];
  const context = vm.createContext({ FormData, request: async (url, options) => { sent.push({ url, options }); } });
  vm.runInContext(source + '\nglobalThis.send = sendUpload;', context);
  await context.send(new Blob(['retained draft']), 'renamed.txt', 'captured-location', 'folder', 'reviewed-token');
  const { url, options } = sent[0];
  assert.equal(url, '/api/files/upload');
  assert.equal(options.method, 'POST');
  assert.equal(options.body.get('location_id'), 'captured-location');
  assert.equal(options.body.get('path'), 'folder');
  assert.equal(options.body.get('expected_etag'), 'reviewed-token');
  assert.equal(options.body.get('file').name, 'renamed.txt');
  assert.equal(await options.body.get('file').text(), 'retained draft');
  await context.send(new Blob(['new file']), 'new.txt', 'new-location', '');
  assert.equal(sent[1].options.body.has('expected_etag'), false);
});

test('Files operation completion refreshes an open listing even when details are visible', () => {
  const queue = files.match(/async function queueOperation\(payload\)[\s\S]*?\n}\n\nasync function loadOperations/)[0];
  assert.match(queue, /currentViewAffected/);
  assert.match(queue, /if \(sameView \|\| currentViewAffected\)\s*\{[\s\S]{0,420}refreshAfterOperation\(refreshTerm\)/);
  assert.doesNotMatch(queue, /sameView && !state\.current/);
});

test('Files operation failures reconcile the listing before another retry', () => {
  const queue = files.match(/async function queueOperation\(payload\)[\s\S]*?\n}\n\nasync function loadOperations/)[0];
  const failure = queue.match(/\.catch\(async error => \{[\s\S]*?\n\s*}\);/)?.[0] || '';
  assert.match(failure, /await loadOperations\(\)/);
  assert.match(failure, /await refreshQueuedOperation\(payload, refreshContext\)/);
});

test('Files operation completion refreshes affected trash and offline views', () => {
  const queue = files.match(/async function queueOperation\(payload\)[\s\S]*?\n}\n\nasync function loadOperations/)[0];
  assert.match(queue, /const affectsCurrentLocation/);
  assert.match(queue, /state\.view !== 'trash'/);
  assert.match(queue, /\['delete', 'restore'\]\.includes\(payload\.action\)/);
  assert.doesNotMatch(queue, /state\.view !== 'offline'/);
});

test('Files trash rows use stable trash identities and block live bulk mutations', () => {
  assert.match(files, /row_key:\s*`trash:\$\{item\.id\}`/);
  assert.match(files, /function itemKey\(item\)/);
  assert.match(files, /state\.view === 'trash' && !\['restore', 'clear'\]\.includes\(action\)/);
  assert.match(files, /state\.view !== 'trash' \|\| !isWritable\(\) \|\| state\.selected\.size !== 1 \|\| selectionRestoreActive/);
  const writeState = files.match(/function applyWriteState\(\)[\s\S]*?\n}\n\nfunction renderFilesLoading/)[0];
  assert.match(writeState, /button\.hidden = trashView/);
  assert.match(writeState, /button\.disabled = !writable \|\| trashView/);
});

test('Files leaves Trash selected until a live search succeeds', () => {
  const search = files.match(/async function searchFiles\(term\)[\s\S]*?\n}\n\nfunction clearFilesSearch/)[0];
  const request = search.indexOf("await request('/api/files/search'");
  const transition = search.indexOf("state.view = 'all'");
  const failure = search.indexOf('} catch (error)');
  assert.match(search, /const searchingTrash = state\.view === 'trash'/);
  assert.ok(request >= 0 && transition > request, 'Trash changes only after search data arrives');
  assert.ok(transition < failure, 'the failed-request path does not switch away from Trash');
});

test('Files search keeps starred results inside the starred collection', () => {
  const search = files.match(/async function searchFiles\(term\)[\s\S]*?\n}\n\nfunction clearFilesSearch/)[0];
  assert.match(search, /if \(state\.view === 'starred'\)/);
  assert.match(search, /filterCurrentItems\(q\)/);
  assert.ok(search.indexOf("state.view === 'starred'") < search.indexOf('/api/files/search'));
});

test('Files filtered derived views drop selections that are no longer visible', () => {
  const reconcile = files.match(/function reconcileSelectionWithVisibleItems\(\)[\s\S]*?\n}/)[0];
  assert.match(reconcile, /new Set\(state\.items\.map\(itemKey\)\)/);
  assert.match(reconcile, /state\.selected\.delete\(key\)/);

  const current = files.match(/function filterCurrentItems\(term\)[\s\S]*?\n}/)[0];
  const offline = files.match(/function filterOfflineItems\(term\)[\s\S]*?\n}/)[0];
  assert.match(current, /reconcileSelectionWithVisibleItems\(\)/);
  assert.match(offline, /filterCurrentItems\(term\)/);
});

test('Files keeps an active Starred filter after reloading the collection', () => {
  const currentView = files.match(/async function loadCurrentView\(\)[\s\S]*?\n}\n\nfunction syncViewButtons/)[0];
  assert.match(
    currentView,
    /\(view === 'offline' \|\| view === 'starred'\)[\s\S]{0,100}filterCurrentItems\(state\.searchTerm\)/,
  );
});

test('Files clears derived-view backing items before and after a failed request', () => {
  const currentView = files.match(/async function loadCurrentView\(\)[\s\S]*?\n}\n\nfunction syncViewButtons/)[0];
  const requestStart = currentView.indexOf('beginFilesRequest(host)');
  const firstClear = currentView.indexOf('state.viewItems = []');
  const catchStart = currentView.indexOf('} catch (error) {');
  const failureClear = currentView.indexOf('state.viewItems = []', firstClear + 1);
  assert.ok(firstClear >= 0 && firstClear < requestStart);
  assert.ok(failureClear > catchStart);
});

test('Files never offers a raw download action for a directory', () => {
  const details = files.match(/async function renderDetails\(item\)[\s\S]*?\n}\n\nasync function loadVersions/)[0];
  assert.match(details, /readable && item\.type !== 'dir'[\s\S]{0,180}download/);
});

test('Files retries transient index polling failures for the same location', () => {
  const status = files.match(/async function loadIndexStatus\([^)]*\)[\s\S]*?\n}\n\nfunction scheduleIndexPoll/)[0];
  assert.match(status, /catch/);
  assert.match(status, /locationId !== state\.locationId/);
  assert.match(status, /scheduleIndexPoll\(locationId, 1500\)/);
});

test('Files shows indexing immediately instead of waiting for the background request', () => {
  const indexing = files.match(/async function startIndexing\(\)[\s\S]*?\n}\n\nfunction applyWriteState/)[0];
  const request = indexing.indexOf('await request');
  assert.ok(indexing.indexOf("state: 'queued'") >= 0);
  assert.ok(indexing.indexOf("state: 'queued'") < request);
  assert.ok(indexing.indexOf('renderLocationStatus()') < request);
  assert.ok(indexing.indexOf('scheduleIndexPoll(locationId)') < request);
});

test('Files location tests ignore responses after the selected location changes', () => {
  const connection = files.match(/async function testLocation\(\)[\s\S]*?\n}\n\nasync function changeLocationAccess/)[0];
  assert.match(connection, /const locationId = location\.id/);
  assert.equal((connection.match(/if \(locationId !== state\.locationId\) return/g) || []).length, 2);
});

test('Files closes stale details before changing storage location identity', () => {
  const events = files.match(/function bindEvents\(\)[\s\S]*?\n}\n\nexport function initFiles/)[0];
  const locationChange = events.match(/\$\('files-location-list'\)\?\.addEventListener\('click',[\s\S]*?\n  \}\);/)[0];
  assert.match(locationChange, /closeDetails\(\)/);
  assert.ok(locationChange.indexOf('closeDetails()') < locationChange.indexOf('state.locationId ='));
});

test('Files clears stale actions before a new folder request starts', () => {
  const start = files.match(/function beginFilesRequest\(host\)[\s\S]*?\n}/)[0];
  assert.ok(start.indexOf('state.selected.clear()') < start.indexOf('renderFilesLoading(host)'));
  assert.ok(start.indexOf('renderSelection()') < start.indexOf('renderFilesLoading(host)'));
  assert.ok(start.indexOf('closeDetails()') < start.indexOf('renderFilesLoading(host)'));
  const listing = files.match(/export async function loadFiles\([^)]*\)[\s\S]*?\n}\n\nasync function loadCurrentView/)[0];
  assert.ok(listing.indexOf('beginFilesRequest(host)') < listing.indexOf("'/api/files/list'"));
});

test('Files commits offline state only for the current listing generation', () => {
  const listing = files.match(/export async function loadFiles\([^)]*\)[\s\S]*?\n}\n\nasync function loadCurrentView/)[0];
  assert.match(listing, /const offline = await loadOfflineState\(locationId, fetcher\)/);
  assert.ok(
    listing.indexOf('if (sequence !== viewSequence || locationId !== state.locationId) return;', listing.indexOf('const offline ='))
      < listing.indexOf('state.offline = offline'),
  );
});

test('Files keeps explicit offline roots separate from cached descendants', () => {
  const currentView = files.match(/async function loadCurrentView\(\)[\s\S]*?\n}\n\nfunction renderBreadcrumb/)[0];
  assert.match(currentView, /const explicitOffline = state\.cwd[\s\S]*?await loadOfflineState\(locationId\)/);
  assert.match(currentView, /state\.offline = explicitOffline/);
  assert.match(files, /item\.cache_only && !current/);
});

test('Files location removal preserves a newer location selection', () => {
  const removal = files.match(/async function removeLocation\(\)[\s\S]*?\n}\n\nfunction dialogFocusables/)[0];
  assert.match(removal, /const locationId = location\.id/);
  assert.match(removal, /if \(state\.locationId !== locationId\) \{[\s\S]*?await loadLocations\(\);[\s\S]*?return;/);
  assert.ok(removal.indexOf('if (state.locationId !== locationId)') < removal.indexOf("state.locationId = ''"));
});

test('Files retries the exact folder or search request that failed', () => {
  assert.match(files, /let filesRetry = null/);
  assert.match(files, /renderFilesError\(host, error, \(\) => loadFiles\(path\)\)/);
  assert.match(files, /renderFilesError\(host, error, \(\) => searchFiles\(q\)\)/);
  const retry = files.match(/if \(event\.target\.closest\('\[data-files-retry\]'\)\)[\s\S]{0,180}/)[0];
  assert.match(retry, /filesRetry/);
  assert.doesNotMatch(retry, /loadCurrentView\(\)/);
});

test('Files operation refreshes preserve the active search generation', () => {
  const queue = files.match(/async function queueOperation\(payload\)[\s\S]*?\n}\n\nasync function loadOperations/)[0];
  assert.match(queue, /searchTerm: state\.searchTerm/);
  assert.match(queue, /state\.searchTerm === refreshContext\.searchTerm/);
  assert.match(queue, /const refreshTerm = sameView \? refreshContext\.searchTerm : state\.searchTerm/);
  assert.match(queue, /refreshAfterOperation\(refreshTerm\)/);
});

test('Files exposes a start action for a queued operation left behind by an interrupted request', () => {
  const operations = files.match(/function renderOperations\(\)[\s\S]*?\n}\n\nasync function operationAction/)[0];
  assert.match(operations, /operation\.can_run/);
  assert.match(operations, /data-operation-action="run"/);
});

test('Files operation actions preserve an active search', () => {
  const action = files.match(/async function operationAction\(id, action\)[\s\S]*?\n}\n\nasync function undoOperation/)[0];
  assert.match(action, /refreshAfterOperation\(\)/);
});

test('Files offline browsing and previews stay on cached endpoints', () => {
  const currentView = files.match(/async function loadCurrentView\(\)[\s\S]*?\n}\n\nasync function refreshAfterOperation/)[0];
  assert.match(currentView, /\/api\/files\/offline\/list/);
  assert.match(currentView, /filterCurrentItems\(state\.searchTerm\)/);
  const open = files.match(/function openItem\(item\)[\s\S]*?\n}\n\nasync function renderDetails/)[0];
  assert.match(open, /state\.view === 'offline'/);
  assert.match(open, /loadCurrentView\(\)/);
  const details = files.match(/async function renderDetails\(item\)[\s\S]*?\n}\n\nasync function loadVersions/)[0];
  assert.match(details, /\/api\/files\/offline\/raw/);
  const preview = files.match(/async function openPreview\(item\)[\s\S]*?\n}\n\nfunction closePreview/)[0];
  assert.match(preview, /\/api\/files\/offline\/raw/);
  assert.match(preview, /\/api\/files\/offline\/read/);
  const search = files.match(/async function searchFiles\(term\)[\s\S]*?\n}\n\nfunction clearFilesSearch/)[0];
  assert.match(search, /if \(state\.view === 'offline'\)/);
  assert.match(search, /filterOfflineItems\(q\)/);
  assert.ok(search.indexOf("state.view === 'offline'") < search.indexOf('/api/files/search'));
  const writeState = files.match(/function applyWriteState\(\)[\s\S]*?\n}\n\nfunction renderFilesLoading/)[0];
  assert.match(writeState, /const cacheView = state\.view === 'offline'/);
  assert.match(writeState, /button\.hidden = trashView \|\| cacheView/);
});

test('Escape closes the preview before the underlying details panel', () => {
  const keyboard = files.match(/document\.addEventListener\('keydown',[\s\S]*?\n  \}\);\n}/)[0];
  const preview = keyboard.indexOf("files-preview-modal");
  const details = keyboard.indexOf("files-detail-panel");
  assert.ok(preview >= 0, 'preview branch is present');
  assert.ok(details > preview, 'preview is handled before details');
});

function filesViewportHarness(options = {}) {
  const box = options.box || { top: 160, bottom: 204 };
  const selectedBox = options.selectedBox || box;
  const writes = new Map();
  const bar = { hidden: true };
  const count = { textContent: '' };
  const header = { getBoundingClientRect: () => ({ bottom: 150, height: 53 }) };
  const dock = {
    hidden: false,
    getBoundingClientRect: () => ({ height: 239.2 }),
  };
  const styles = new Map([
    [header, { position: options.headerPosition || 'sticky' }],
    [dock, { position: 'fixed', bottom: '8.5px' }],
  ]);
  const view = {
    scrollTop: 40, scrollLeft: 13, clientTop: 0, clientHeight: 353,
    getBoundingClientRect: () => ({ top: 97, bottom: 450 }),
    contains: () => options.foreign !== true,
    style: { setProperty: (name, value) => writes.set(name, value) },
  };
  let focusCalls = 0;
  const item = {
    getBoundingClientRect: () => {
      const current = bar.hidden ? box : selectedBox;
      const scrollDelta = view.scrollTop - 40;
      return { top: current.top - scrollDelta, bottom: current.bottom - scrollDelta };
    },
    focus: () => { focusCalls += 1; },
  };
  const target = {
    closest: () => options.unrelated ? null : item,
    matches: () => options.keyboard !== false,
    focus: () => { focusCalls += 1; },
  };
  const document = { activeElement: target };
  const selected = new Map([['owned.txt', { path: 'owned.txt' }]]);
  let writeStateCalls = 0;
  const nodes = {
    'files-view': view, 'files-app-header': header, 'files-operation-dock': dock,
    'files-selection-bar': bar, 'files-selection-count': count,
  };
  const source = ['revealFileControl', 'updateOperationClearance', 'renderSelection']
    .map(name => {
      const body = files.match(new RegExp(`function ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n\\}`))?.[0];
      assert.ok(body, `actual ${name} function is present`);
      return body;
    }).join('\n');
  const context = vm.createContext({
    $: id => nodes[id], document, state: { selected },
    innerHeight: options.innerHeight || 450,
    getComputedStyle: element => styles.get(element),
    applyWriteState: () => { writeStateCalls += 1; },
  });
  vm.runInContext(source + '\nglobalThis.actions = { revealFileControl, updateOperationClearance, renderSelection };', context);
  return {
    ...context.actions, view, header, dock, styles, writes, nodes, target, document,
    bar, count, selected, focusCalls: () => focusCalls, writeStateCalls: () => writeStateCalls,
  };
}

test('Files vertical reveal moves only enough to expose a row below the sticky header or above the viewport bottom', () => {
  const top = filesViewportHarness({ box: { top: 140, bottom: 184 } });
  top.revealFileControl(top.target);
  assert.equal(top.view.scrollTop, 30);
  assert.equal(top.view.scrollLeft, 13);
  assert.equal(top.document.activeElement, top.target);
  assert.equal(top.focusCalls(), 0);

  const bottom = filesViewportHarness({ box: { top: 420, bottom: 464 } });
  bottom.revealFileControl(bottom.target);
  assert.equal(bottom.view.scrollTop, 54);
  bottom.revealFileControl(bottom.target);
  assert.equal(bottom.view.scrollTop, 54, 'already revealed control does not keep scrolling');

  const shorterRoot = filesViewportHarness({ box: { top: 369, bottom: 413 } });
  shorterRoot.view.clientHeight = 300;
  shorterRoot.revealFileControl(shorterRoot.target);
  assert.equal(shorterRoot.view.scrollTop, 56, 'use the Files scrollport bottom397, not window bottom450');

  const shorterWindow = filesViewportHarness({ box: { top: 396, bottom: 440 }, innerHeight: 430 });
  shorterWindow.revealFileControl(shorterWindow.target);
  assert.equal(shorterWindow.view.scrollTop, 50, 'use the visible viewport when it ends before the root');
});

test('Files vertical reveal preserves visible controls and leaves a control spanning both bounds unresolved', () => {
  for (const box of [
    { top: 160, bottom: 204 }, { top: 150, bottom: 194 },
    { top: 406, bottom: 450 }, { top: 140, bottom: 460 },
  ]) {
    const h = filesViewportHarness({ box });
    h.revealFileControl(h.target);
    assert.equal(h.view.scrollTop, 40, JSON.stringify(box));
    assert.equal(h.view.scrollLeft, 13);
    assert.equal(h.focusCalls(), 0);
  }
});

test('Files vertical reveal ignores nonsticky layouts and controls outside its scope', () => {
  for (const options of [{ headerPosition: 'static' }, { foreign: true }, { unrelated: true }]) {
    const h = filesViewportHarness({ ...options, box: { top: 140, bottom: 184 } });
    h.revealFileControl(h.target);
    h.revealFileControl(null);
    assert.equal(h.view.scrollTop, 40);
    assert.equal(h.view.scrollLeft, 13);
    assert.equal(h.document.activeElement, h.target);
    assert.equal(h.focusCalls(), 0);
  }
});

test('Files operation clearance follows floating versus in-flow and hidden docks, without stale header clearance', () => {
  const h = filesViewportHarness();
  h.updateOperationClearance();
  assert.equal(h.writes.get('--files-operation-clearance'), '256px');
  assert.equal(h.writes.get('--files-header-clearance'), '53px');

  h.styles.set(h.dock, { position: 'absolute', bottom: '16px' });
  h.dock.getBoundingClientRect = () => ({ height: 100 });
  h.updateOperationClearance();
  assert.equal(h.writes.get('--files-operation-clearance'), '124px');

  for (const position of ['static', 'relative']) {
    h.styles.set(h.dock, { position, bottom: '16px' });
    h.updateOperationClearance();
    assert.equal(h.writes.get('--files-operation-clearance'), '0px');
  }
  h.styles.set(h.dock, { position: 'fixed', bottom: 'auto' });
  h.updateOperationClearance();
  assert.equal(h.writes.get('--files-operation-clearance'), '108px');
  h.dock.hidden = true;
  h.styles.set(h.header, { position: 'static' });
  h.updateOperationClearance();
  assert.equal(h.writes.get('--files-operation-clearance'), '0px');
  assert.equal(h.writes.get('--files-header-clearance'), '0px');
  assert.equal(h.view.scrollTop, 40);
  assert.equal(h.view.scrollLeft, 13);
});

test('Files selection reveal follows the changed layout without stealing keyboard or pointer focus', () => {
  for (const keyboard of [true, false]) {
    const h = filesViewportHarness({ keyboard, box: { top: 350, bottom: 396 }, selectedBox: { top: 420, bottom: 466 } });
    const selectedItem = h.selected.get('owned.txt');
    h.renderSelection();
    assert.equal(h.bar.hidden, false);
    assert.equal(h.count.textContent, '1 selected');
    assert.equal(h.view.scrollTop, 56, 'reveal after the selection bar changes layout');
    assert.equal(h.view.scrollLeft, 13);
    assert.equal(h.selected.get('owned.txt'), selectedItem);
    assert.equal(h.document.activeElement, h.target);
    assert.equal(h.focusCalls(), 0);
    assert.equal(h.writeStateCalls(), 1);

    h.selected.clear();
    h.renderSelection();
    assert.equal(h.bar.hidden, true);
    assert.equal(h.count.textContent, '0 selected');
    assert.equal(h.view.scrollTop, 56, 'clearing selection leaves the now-visible row in place');
    assert.equal(h.document.activeElement, h.target);
    assert.equal(h.focusCalls(), 0);
    assert.equal(h.writeStateCalls(), 2);
  }
});

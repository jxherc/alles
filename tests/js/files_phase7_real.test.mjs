import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
const files = readFileSync(new URL('../../static/js/filesphase7.js', import.meta.url), 'utf8');
const dialog = readFileSync(new URL('../../static/js/dialog.js', import.meta.url), 'utf8');
const css = readFileSync(new URL('../../static/kokuen.css', import.meta.url), 'utf8');
const serviceWorker = readFileSync(new URL('../../static/sw.js', import.meta.url), 'utf8');

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
  const noqueueLiteral = serviceWorker.match(/const NOQUEUE = (\[[^;]+\]);/)?.[1] || '[]';
  const noqueue = Function(`return ${noqueueLiteral}`)();
  const pathSource = serviceWorker.match(/function replayPolicyPathname\(url\) \{[\s\S]*?\n\}/)?.[0] || '';
  const filterSource = serviceWorker.match(/function mustQuarantineOutboxItem\(rawUrl\) \{[\s\S]*?\n\}/)?.[0] || '';
  const flushSource = serviceWorker.match(/async function flushOutbox\(\) \{[\s\S]*?\n\}/)?.[0] || '';
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
  const flush = Function(
    'NOQUEUE',
    '_all',
    '_del',
    '_put',
    'fetch',
    'notifyClients',
    'self',
    `${pathSource}\n${filterSource}\n${flushSource}\nreturn flushOutbox;`,
  )(
    noqueue,
    async () => rows,
    async id => { deleted.push(id); },
    async item => { blocked.push(item); },
    async url => { fetched.push(url); return { ok: true, status: 200 }; },
    async () => {},
    { location: { origin: 'https://alles.test' } },
  );

  await flush();

  assert.deepEqual(fetched, ['https://alles.test/api/files/tags']);
  assert.deepEqual(deleted, [2]);
  assert.deepEqual(blocked.map(item => item.id), [1, 3, 4, 5, 6, 7, 8]);
  assert.ok(blocked.every(item => item.blocked_reason === 'replay_policy_changed'));
});

test('only an explicit owner action discards quarantined outbox rows', async () => {
  const discardSource = serviceWorker.match(/async function discardBlockedOutbox\(\) \{[\s\S]*?\n\}/)?.[0] || '';
  const deleted = [];
  let notified = 0;
  const discard = Function(
    '_all', '_del', 'notifyClients',
    `${discardSource}\nreturn discardBlockedOutbox;`,
  )(
    async () => [
      { id: 1, blocked_reason: 'replay_policy_changed' },
      { id: 2 },
      { id: 3, blocked_reason: 'replay_policy_changed' },
    ],
    async id => { deleted.push(id); },
    async () => { notified += 1; },
  );

  await discard();

  assert.deepEqual(deleted, [1, 3]);
  assert.equal(notified, 1);
  assert.match(serviceWorker, /alles-discard-blocked/);
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
  assert.match(app, /from '\.\/filesphase7\.js\?v=273'/);
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
    'files-home-btn',
    'files-breadcrumb',
    'files-app-status',
    'files-settings-btn',
  ]) {
    assert.match(view, new RegExp(`id="${id}"`), id);
  }
  assert.match(css, /body\[data-app="files"\] \.main > \.topbar\s*\{\s*display:\s*none\s*!important;/);
  assert.match(app, /getElementById\('files-home-btn'\)[\s\S]{0,260}(?:navigateTo|crossNav)/);
  assert.match(app, /getElementById\('files-settings-btn'\)[\s\S]{0,160}openSettings/);
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
  const restore = files.match(/async function restoreItem\(item\)[\s\S]*?\n}\n\nfunction photosImportMessage/)[0];
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
  assert.match(upload, /body\.append\('location_id', locationId\)/);
  assert.match(upload, /body\.append\('path', cwd\)/);
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

test('Files version responses stay bound to the detail request that opened them', () => {
  assert.match(files, /let detailSequence = 0/);
  assert.match(files, /const detailRequest = \+\+detailSequence/);
  assert.match(files, /loadVersions\(path, locationId, detailRequest\)/);
  const versions = files.match(/async function loadVersions\(path, locationId, detailRequest\)[\s\S]*?\n}\n\nfunction closeDetails/)[0];
  assert.match(versions, /detailRequest !== detailSequence/);
  assert.match(versions, /locationId !== state\.locationId/);
  assert.match(versions, /state\.current !== item/);
  assert.match(versions, /panel\.hidden/);
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
  assert.match(files, /state\.view === 'trash' && action !== 'clear'/);
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
  const locationChange = events.match(/\$\('files-location-list'\)[\s\S]*?\n  \}\);/)[0];
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
